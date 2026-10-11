import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { ChibiScene, disposeModel } from './chibi-scene.js';
import { setupStageControls } from './stage-controls.js';
import { setupGifControls } from './gif-controls.js';
import { createStudioLogo } from './studio-logo.js';

const $ = selector => document.querySelector(selector);
const viewport = $('#viewport');
const logo = createStudioLogo($('#studio-logo'));
let scene, library = [], models = [], characters = [], loadToken = 0, currentEntry = null, pendingFetch = null;
let libraryRegion = 'global', refreshing = false;
try { if (localStorage.getItem('chibi-studio-region') === 'jp') libraryRegion = 'jp'; } catch { }
const selectionKey = region => region === 'jp' ? 'chibi-studio-model-jp' : 'chibi-studio-model';
const inLibrary = (entry, region) => (entry.available_in || [entry.region || 'global']).includes(region);
const maxBytes = 80 * 1024 * 1024;

function status(text, state = '') { $('#status').textContent = text; $('#status').dataset.state = state; }
function error(message) { $('#message').textContent = message; $('#message').hidden = false; }
function options(select, entries) { select.replaceChildren(...entries.map(([value, text]) => new Option(text, value))); }
function characterKey(entry) { return String(entry.character_id || entry.id || ''); }
function displayName(entry) { return entry.display_name || (entry.id && entry.outfit ? `${entry.name} — ${entry.outfit}` : entry.name); }
function searchable(text) { return text.normalize('NFKD').replace(/\p{Diacritic}/gu, '').toLocaleLowerCase(); }
function showCharacters() {
  const query = searchable($('#character-search').value.trim());
  const matches = characters.filter(character => searchable(`${character.name} ${character.id} ${character.outfits.map(entry => `${entry.name_jp || ''} ${entry.outfit} ${entry.outfit_jp || ''}`).join(' ')}`).includes(query));
  options($('#character'), matches.length ? matches.map(character => [character.id, character.name]) : [['', 'No matching characters']]);
  $('#character').disabled = !matches.length;
  const currentId = currentEntry ? characterKey(currentEntry) : '';
  if (matches.some(character => character.id === currentId)) $('#character').value = currentId;
  else if (matches.length && (currentEntry || query)) $('#character').add(new Option('Choose a character', '', true, true), 0);
}
function showOutfits(characterId, preferredId) {
  const character = characters.find(entry => entry.id === characterId);
  const outfits = character?.outfits || [];
  options($('#outfit'), outfits.length ? outfits.map(entry => [entry.id, entry.outfit]) : [['', 'Choose a character first']]);
  $('#outfit').disabled = outfits.length < 2;
  const selected = outfits.find(entry => entry.id === preferredId) || outfits.find(entry => entry.costume === '00') || outfits[0];
  if (selected) { $('#outfit').value = selected.id; $('#outfit').title = displayName(selected); }
  return selected;
}
function showMotions() {
  const category = $('#motion-category').value;
  const labels = currentEntry?.animation_labels || {}, groups = currentEntry?.animation_groups || {};
  const matching = scene.clips.map((clip, index) => ({clip, index, group: groups[clip.name] || 'Other'}))
    .filter(entry => !category || entry.group === category);
  const select = $('#animation');
  select.replaceChildren();
  const sections = new Map();
  for (const {clip, index, group} of matching) {
    if (!sections.has(group)) {
      const section = document.createElement('optgroup'); section.label = group;
      sections.set(group, section); select.append(section);
    }
    sections.get(group).append(new Option(labels[clip.name] || clip.name || `Motion ${index + 1}`, index));
  }
  if (!matching.length) select.add(new Option('No animation clips in this file', ''));
  const selected = matching.find(entry => entry.index === scene.clipIndex) || matching[0];
  if (selected) {
    select.value = String(selected.index);
    if (scene.clipIndex !== selected.index) chooseMotion(selected.index);
  }
}
function chooseExpression(name, manual = false) {
  if (!scene.faceConfig.presets?.[name]) name = 'neutral';
  scene.setExpression(name);
  if (manual) $('#match-expression').checked = false;
  document.querySelectorAll('[data-expression]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.expression === name)));
}
function matchExpression() {
  if (!$('#match-expression').checked) return;
  const name = scene.clips[scene.clipIndex]?.name || '';
  const expression = /tired/.test(name) ? 'tired' : /laugh/.test(name) ? 'laughing' : /ikaku/.test(name) ? 'angry' :
    /surprise|_oh\d/.test(name) ? 'surprised' : /request/.test(name) ? 'worried' : /shy|_bit\d/.test(name) ? 'shy' :
    /gatts|fight|run/.test(name) ? 'determined' : /hungry/.test(name) ? 'drooling' :
    /idea|hope|good/.test(name) ? 'excited' : /akire|soppo|udekumi/.test(name) ? 'unimpressed' : /dance|joy|happy|yell|music/.test(name) ? 'happy' :
    /hello|bow|clap|come|skip/.test(name) ? 'smile' : 'neutral';
  chooseExpression(expression);
}
function chooseMotion(index) { scene.playClip(index); matchExpression(); }
function showExpressions(enabled) {
  const names = Object.keys(scene.faceConfig.presets || {});
  $('#expressions').replaceChildren(...names.map(name => {
    const button = document.createElement('button');
    button.dataset.expression = name;
    button.textContent = name.charAt(0).toUpperCase() + name.slice(1).replaceAll('_', ' ');
    button.disabled = !enabled;
    button.setAttribute('aria-pressed', String(name === scene.expression));
    button.onclick = () => chooseExpression(name, true);
    return button;
  }));
  $('#match-expression').disabled = !enabled;
  matchExpression();
}
function syncPlayback() {
  const button = $('#play-pause');
  const label = scene.playing ? 'Pause animation' : 'Play animation';
  button.dataset.playing = String(scene.playing);
  button.setAttribute('aria-label', label);
  button.title = label;
}

// GLB imports are self-contained: loading one must not request remote files or local API routes.
function inspectGlb(buffer) {
  if (buffer.byteLength > maxBytes) throw new Error('Please use a GLB smaller than 80 MB.');
  if (buffer.byteLength < 20) throw new Error('This is not a complete GLB file.');
  const view = new DataView(buffer);
  if (view.getUint32(0, true) !== 0x46546c67 || view.getUint32(4, true) !== 2 || view.getUint32(8, true) !== buffer.byteLength) throw new Error('Please choose a valid glTF 2 GLB file.');
  const length = view.getUint32(12, true);
  if (view.getUint32(16, true) !== 0x4e4f534a || length > buffer.byteLength - 20) throw new Error('The GLB metadata is incomplete.');
  let data;
  try { data = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 20, length))); }
  catch { throw new Error('The GLB metadata could not be read.'); }
  for (const resource of [...(data.buffers || []), ...(data.images || [])]) {
    if (resource.uri && !resource.uri.startsWith('data:')) throw new Error('Please export a self-contained GLB with its textures embedded.');
  }
  if ((data.extensionsRequired || []).some(name => /draco|meshopt|basisu/.test(name))) throw new Error('This preview needs an uncompressed GLB. Export without Draco, meshopt or KTX2 compression.');
  return data;
}

async function loadModel(entry, file) {
  if (scene.capturing) return;
  const token = ++loadToken;
  pendingFetch?.abort();
  pendingFetch = new AbortController();
  $('#loading').hidden = false;
  $('#message').hidden = true;
  status('Loading');
  try {
    let buffer;
    if (file) {
      if (file.size > maxBytes) throw new Error('Please use a GLB smaller than 80 MB.');
      buffer = await file.arrayBuffer();
    } else {
      const response = await fetch(entry.model_url, {signal: pendingFetch.signal});
      if (!response.ok) throw new Error('This character is unavailable. Refresh the character list to try again.');
      if (Number(response.headers.get('content-length')) > maxBytes) throw new Error('Please use a GLB smaller than 80 MB.');
      buffer = await response.arrayBuffer();
    }
    const json = inspectGlb(buffer);
    entry.physics = json.extras?.umaPhysics;
    const gltf = await new GLTFLoader().parseAsync(buffer, '');
    if (token !== loadToken) { disposeModel(gltf.scene); return; }
    if (file) {
      const character = json.extras?.umaCharacter;
      if (typeof character?.name === 'string' && character.name.trim()) {
        entry.name = character.name.slice(0, 120);
        if (typeof character.outfit === 'string' && character.outfit.trim()) {
          entry.outfit = character.outfit.slice(0, 120);
          entry.display_name = `${entry.name} — ${entry.outfit}`;
        }
      }
      entry.faces = json.extras?.umaFaces;
      entry.animation_labels = json.extras?.umaAnimations?.labels || {};
      entry.animation_groups = json.extras?.umaAnimations?.groups || {};
    }
    const stats = scene.setModel(gltf, entry);
    currentEntry = entry;
    $('#empty-state').hidden = true;
    $('#stage-name').textContent = displayName(entry);
    $('#outfit').title = displayName(entry);
    const groups = entry.animation_groups || {};
    const categories = [...new Set(scene.clips.map(clip => groups[clip.name] || 'Other'))];
    options($('#motion-category'), [['', 'All motions'], ...categories.map(name => [name, name])]);
    $('#motion-category').disabled = categories.length < 2;
    showMotions();
    $('#animation').disabled = $('#play-pause').disabled = $('#timeline').disabled = $('#speed').disabled = !scene.clips.length;
    $('#clip-count').textContent = `${scene.clips.length} clip${scene.clips.length === 1 ? '' : 's'}`;
    for (const id of ['reset-camera', 'save-image', 'turntable']) $(`#${id}`).disabled = false;
    $('#save-gif').disabled = !scene.clips.length;
    $('#cloth-physics').disabled = !stats.physics;
    $('#cloth-physics').checked = scene.physicsEnabled;
    $('#physics-note').textContent = stats.physics ? 'Sleeves, hair and clothing follow the motion. Included in GIFs.' : 'Secondary motion becomes available with cloth data in the character export.';
    showExpressions(stats.faceControls);
    $('#blink').disabled = !stats.faceControls;
    $('#face-note').hidden = stats.faceControls;
    $('#model-details').textContent = `${stats.meshes} meshes · ${stats.triangles.toLocaleString()} triangles · ${stats.bones} bones · ${stats.animations} animations · ${(buffer.byteLength / 1048576).toFixed(1)} MB. ${file ? 'Opened in your browser; no file uploaded.' : 'Loaded from the character library.'}`;
    viewport.dataset.loaded = 'true';
    viewport.dataset.model = entry.id || '';
    viewport.dataset.animations = String(stats.animations);
    if (entry.id) { try { localStorage.setItem(selectionKey(libraryRegion), entry.id); } catch { } }
    syncPlayback();
    status('Ready', 'ready');
  } catch (err) {
    if (token !== loadToken || err.name === 'AbortError') return;
    error(err.message || 'The character could not be opened. Try another GLB file.');
    status(currentEntry ? 'Previous character kept' : 'Could not load', 'error');
  } finally {
    if (token === loadToken) $('#loading').hidden = true;
  }
}

function syncLibraryButton() {
  const button = $('#library-toggle');
  const next = libraryRegion === 'jp' ? 'Global' : 'JP';
  button.title = `Switch to the ${next} library`;
  button.setAttribute('aria-label', button.title);
  button.setAttribute('aria-pressed', String(libraryRegion === 'jp'));
  $('#library-region-label').textContent = libraryRegion === 'jp' ? 'JP' : 'Global';
  button.disabled = refreshing || !library.some(entry => inLibrary(entry, libraryRegion === 'jp' ? 'global' : 'jp'));
  document.documentElement.dataset.libraryRegion = libraryRegion;
}

async function showLibrary(switching = false) {
  models = library.filter(entry => inLibrary(entry, libraryRegion));
  syncLibraryButton();
  const grouped = new Map();
  models.forEach(entry => {
    const key = characterKey(entry);
    if (!grouped.has(key)) grouped.set(key, {id: key, name: entry.name, outfits: []});
    grouped.get(key).outfits.push(entry);
  });
  characters = [...grouped.values()].sort((a, b) => a.name.localeCompare(b.name));
  characters.forEach(character => character.outfits.sort((a, b) => (a.costume || '').localeCompare(b.costume || '')));
  $('#library-count').textContent = `${libraryRegion === 'jp' ? 'JP' : 'Global'} · ${characters.length} character${characters.length === 1 ? '' : 's'} · ${models.length} outfit${models.length === 1 ? '' : 's'}`;
  showCharacters();
  let savedId;
  try { savedId = localStorage.getItem(selectionKey(libraryRegion)); } catch { }
  const preferredId = switching ? savedId : (currentEntry?.id || savedId);
  // Preserve selections saved before the studio adopted the shared JP models.
  const selected = models.find(entry => entry.id === preferredId || entry.id === `jp-${preferredId}`) ||
    (switching && (models.find(entry => characterKey(entry) === characterKey(currentEntry || {}) && entry.costume === currentEntry?.costume) ||
      models.find(entry => characterKey(entry) === characterKey(currentEntry || {})))) ||
    ((!currentEntry || switching) && characters[0]?.outfits[0]);
  if (selected && scene) {
    $('#character').value = characterKey(selected);
    showOutfits(characterKey(selected), selected.id);
    await loadModel(selected);
  } else if (currentEntry) {
    $('#character').add(new Option(currentEntry.name, '', true, true));
    options($('#outfit'), [['', currentEntry.outfit || 'Outfit from file']]); $('#outfit').disabled = true;
  } else { showOutfits(''); status('Waiting for a character'); }
  void logo.setLibrary(library);
}

async function refreshModels() {
  if (refreshing || scene.capturing) return;
  refreshing = true;
  $('#refresh-models').disabled = true;
  syncLibraryButton();
  try {
    const response = await fetch('/api/chibi-models');
    if (!response.ok) throw new Error('The character list is unavailable. You can still open a GLB file.');
    library = (await response.json()).models || [];
    if (library.length && !library.some(entry => inLibrary(entry, libraryRegion))) libraryRegion = library[0].available_in?.[0] || library[0].region || 'global';
    await showLibrary();
  } catch (err) { error(err.message); status('Character list unavailable', 'error'); }
  finally { refreshing = false; $('#refresh-models').disabled = false; syncLibraryButton(); }
}

async function switchLibrary() {
  if (refreshing || scene.capturing) return;
  libraryRegion = libraryRegion === 'jp' ? 'global' : 'jp';
  try { localStorage.setItem('chibi-studio-region', libraryRegion); } catch { }
  $('#character-search').value = '';
  await showLibrary(true);
}

function openFile(file) {
  if (!file) return;
  if (!/\.glb$/i.test(file.name)) { error('Choose a self-contained .glb file to open in the viewer.'); return; }
  const entry = {name: file.name.replace(/\.glb$/i, '').replace(/[_-]/g, ' '), outfit: 'Opened from a file'};
  loadModel(entry, file).then(() => {
    if (currentEntry !== entry) return;
    for (const option of [...$('#character').options]) if (!option.value) option.remove();
    $('#character').add(new Option(entry.name, '', true, true));
    options($('#outfit'), [['', entry.outfit]]); $('#outfit').disabled = true;
  });
}

try {
  scene = new ChibiScene(viewport, ({time, duration}) => {
    if (document.activeElement !== $('#timeline')) $('#timeline').value = duration ? time / duration : 0;
    $('#time-label').textContent = `${Math.floor(time / 60)}:${String(Math.floor(time % 60)).padStart(2, '0')}`;
  });
  $('#blink').checked = scene.blink;
  syncPlayback();
  $('#open-model').onclick = $('#empty-open').onclick = () => $('#model-file').click();
  $('#model-file').onchange = event => { openFile(event.target.files[0]); event.target.value = ''; };
  $('#character-search').oninput = () => { showCharacters(); showOutfits($('#character').value, currentEntry?.id); };
  $('#character').onchange = () => { const entry = showOutfits($('#character').value, currentEntry?.id); if (entry) loadModel(entry); };
  $('#outfit').onchange = () => { const entry = models.find(model => model.id === $('#outfit').value); if (entry) loadModel(entry); };
  $('#refresh-models').onclick = refreshModels;
  $('#library-toggle').onclick = switchLibrary;
  $('#animation').onchange = () => chooseMotion(Number($('#animation').value));
  $('#motion-category').onchange = showMotions;
  $('#match-expression').onchange = matchExpression;
  $('#cloth-physics').onchange = () => scene.setPhysics($('#cloth-physics').checked);
  $('#play-pause').onclick = () => { scene.playing = !scene.playing; syncPlayback(); };
  $('#timeline').oninput = () => scene.seek(Number($('#timeline').value));
  $('#speed').onchange = () => { scene.speed = Number($('#speed').value); };
  $('#blink').onchange = () => { scene.blink = $('#blink').checked; scene.applyFace(false); };
  $('#turntable').onchange = () => { scene.controls.autoRotate = $('#turntable').checked; };
  $('#reset-camera').onclick = () => scene.resetCamera();
  $('#save-image').onclick = () => {
    const link = document.createElement('a');
    link.download = `${(currentEntry ? displayName(currentEntry) : 'chibi').replace(/[^\w-]+/g, '-').toLowerCase()}.png`;
    link.href = scene.screenshot(); link.click();
  };
  setupStageControls(scene, error);
  setupGifControls(scene, () => {
    const clip = scene.clips[scene.clipIndex]?.name || 'animation';
    return `${currentEntry ? displayName(currentEntry) : 'chibi'}-${currentEntry?.animation_labels?.[clip] || clip}`;
  });
  viewport.addEventListener('dragover', event => { event.preventDefault(); viewport.classList.add('drag-over'); });
  viewport.addEventListener('dragleave', () => viewport.classList.remove('drag-over'));
  viewport.addEventListener('drop', event => { event.preventDefault(); viewport.classList.remove('drag-over'); openFile(event.dataTransfer.files[0]); });
  window.addEventListener('pagehide', event => {
    if (!event.persisted) { loadToken++; pendingFetch?.abort(); logo.dispose(); scene.dispose(); }
  });
  await refreshModels();
} catch (err) {
  status('3D unavailable', 'error');
  $('#loading').hidden = true;
  $('#empty-state').hidden = true;
  error('This browser could not start 3D rendering. Enable hardware acceleration or try a browser with WebGL 2 support.');
  $('#open-model').disabled = true;
}
