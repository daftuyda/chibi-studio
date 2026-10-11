// Runs in an isolated UmaViewer Mono player through BepInEx 5. No Editor required.
using System;
using System.Collections;
using System.IO;
using System.Linq;
using BepInEx;
using Newtonsoft.Json.Linq;
using UnityEngine;

[BepInPlugin("chibistudio.export", "Chibi Studio Export", "0.1.0")]
public sealed class ChibiStudioExporter : BaseUnityPlugin
{
    private JObject request;
    private string output;
    private bool finished;
    private float started;

    private void Awake()
    {
        var file = Path.Combine(Paths.GameRootPath, "chibi-studio-export.json");
        if (!File.Exists(file)) { enabled = false; return; }
        request = JObject.Parse(File.ReadAllText(file));
        output = Path.GetFullPath((string)request["output"]);
        Directory.CreateDirectory(output);
        started = Time.realtimeSinceStartup;
        Logger.LogInfo("Waiting for UmaViewer's local asset index.");
        StartCoroutine(Guard(Export()));
    }

    private void Update()
    {
        if (!finished && request != null && Time.realtimeSinceStartup - started > 180)
            Fail(new TimeoutException("UmaViewer did not finish the local chibi export within three minutes."));
    }

    private IEnumerator Guard(IEnumerator routine)
    {
        while (!finished)
        {
            bool next;
            try { next = routine.MoveNext(); }
            catch (Exception exception) { Fail(exception); yield break; }
            if (!next) yield break;
            yield return routine.Current;
        }
    }

    private void Fail(Exception exception)
    {
        if (finished) return;
        finished = true;
        Logger.LogError(exception);
        File.WriteAllText(Path.Combine(output, "export-error.txt"), exception.ToString());
        Application.Quit(1);
    }

    private IEnumerator Export()
    {
        while (UmaViewerMain.Instance == null || UmaViewerBuilder.Instance == null ||
               UmaViewerUI.Instance == null || UmaViewerMain.Instance.AbList == null || UmaViewerMain.Instance.AbList.Count == 0)
            yield return null;
        // Scene Start methods finish setting up the preview controllers.
        yield return new WaitForSeconds(3);
        global::Config.Instance.DownloadMissingResources = false;
        var main = UmaViewerMain.Instance;
        var builder = UmaViewerBuilder.Instance;
        if ((string)request["mode"] == "inventory")
        {
            var entries = new JArray(main.AbList.Values.Where(entry => entry.Name.StartsWith("3d/chara/mini/") || entry.Name.StartsWith("3d/motion/mini/"))
                .OrderBy(entry => entry.Name).Select(entry => new JObject {
                    ["name"] = entry.Name, ["present"] = File.Exists(entry.FilePath), ["revision"] = entry.Url,
                    ["missing_dependencies"] = new JArray(UmaAssetManager.SearchAB(main, entry).Where(dependency => !File.Exists(dependency.FilePath)).Select(dependency => dependency.Name)),
                }));
            File.WriteAllText(Path.Combine(output, "inventory.json"), new JObject { ["assets"] = entries }.ToString());
            File.WriteAllText(Path.Combine(output, "export-complete.txt"), DateTime.UtcNow.ToString("O"));
            finished = true;
            Application.Quit(0);
            yield break;
        }
        var motions = main.AbMotions.Where(entry => entry.Name.StartsWith("3d/motion/mini/") &&
            entry.Name.Contains("/body/") && File.Exists(entry.FilePath)).OrderBy(entry => entry.Name).ToList();
        File.WriteAllText(Path.Combine(output, "available-motions.json"), new JArray(motions.Select(entry => entry.Name)).ToString());
        Logger.LogInfo("Local mini motions: " + motions.Count);
        if ((string)request["mode"] == "physics")
        {
            var results = new JArray();
            foreach (JObject item in (JArray)request["items"])
            {
                started = Time.realtimeSinceStartup;
                var folder = Path.GetFullPath((string)item["output"]);
                if (!File.Exists(Path.Combine(folder, "model.glb"))) continue;
                var physics = ReadPhysics(item);
                File.WriteAllText(Path.Combine(folder, "physics.json"), physics.ToString());
                results.Add(new JObject { ["id"] = item["id"], ["sources"] = ((JArray)physics["sources"]).Count });
                File.WriteAllText(Path.Combine(output, "progress.json"), new JObject {
                    ["completed"] = results.Count, ["total"] = ((JArray)request["items"]).Count, ["name"] = item["name"], ["outfit"] = item["outfit"],
                }.ToString());
                UmaAssetManager.UnloadAllBundle(true);
                yield return null;
            }
            File.WriteAllText(Path.Combine(output, "physics-report.json"), results.ToString());
            File.WriteAllText(Path.Combine(output, "export-complete.txt"), DateTime.UtcNow.ToString("O"));
            finished = true;
            Application.Quit(0);
            yield break;
        }
        if ((string)request["mode"] == "batch")
        {
            var items = (JArray)request["items"];
            var results = new JArray();
            var report = new JObject { ["results"] = results, ["unavailable"] = request["unavailable"]?.DeepClone() ?? new JArray(), ["total"] = items.Count };
            foreach (JObject item in items)
            {
                started = Time.realtimeSinceStartup;
                var itemOutput = Path.GetFullPath((string)item["output"]);
                Directory.CreateDirectory(itemOutput);
                Logger.LogInfo($"[{results.Count + 1}/{items.Count}] {item["name"]} - {item["outfit"]}");
                File.WriteAllText(Path.Combine(output, "progress.json"), new JObject {
                    ["completed"] = results.Count, ["total"] = items.Count, ["name"] = item["name"], ["outfit"] = item["outfit"],
                }.ToString());
                var result = new JObject { ["id"] = item["id"], ["name"] = item["name"], ["outfit"] = item["outfit"] };
                if ((bool?)request["force"] != true && CurrentExport(item, itemOutput))
                    result["status"] = "unchanged";
                else
                {
                    var routine = ExportCharacter(item, itemOutput);
                    Exception failure = null;
                    while (true)
                    {
                        bool next;
                        try { next = routine.MoveNext(); }
                        catch (Exception exception) { failure = exception; break; }
                        if (!next) break;
                        yield return routine.Current;
                    }
                    result["status"] = failure == null ? "exported" : "failed";
                    if (failure != null) { result["error"] = failure.ToString(); Logger.LogError(failure); }
                    builder.UnloadUma();
                    yield return null;
                    UmaAssetManager.UnloadAllBundle(true);
                    yield return Resources.UnloadUnusedAssets();
                    GC.Collect();
                }
                results.Add(result);
                File.WriteAllText(Path.Combine(output, "batch-report.json"), report.ToString());
            }
        }
        else
        {
            var routine = ExportCharacter(request, output);
            while (routine.MoveNext()) yield return routine.Current;
        }
        File.WriteAllText(Path.Combine(output, "export-complete.txt"), DateTime.UtcNow.ToString("O"));
        finished = true;
        Application.Quit(0);
    }

    private bool CurrentExport(JObject item, string folder)
    {
        try
        {
            var manifest = JObject.Parse(File.ReadAllText(Path.Combine(folder, "manifest.json")));
            return (string)manifest["import_profile"] == (string)item["import_profile"] &&
                new FileInfo(Path.Combine(folder, "model.glb")).Length > 20;
        }
        catch { return false; }
    }

    private JObject ReadPhysics(JObject item)
    {
        var main = UmaViewerMain.Instance;
        var paths = item["physics_assets"] as JArray;
        if (paths == null)
        {
            var id = (int?)item["character_id"] ?? 1030;
            var costume = (string)item["costume"] ?? "00";
            paths = new JArray($"3d/chara/mini/body/mbdy{id}_{costume}/clothes/pfb_mbdy{id}_{costume}_cloth00");
            var head = $"3d/chara/mini/head/mchr{id}_{costume}/clothes/pfb_mchr{id}_{costume}_cloth00";
            if (!main.AbList.ContainsKey(head)) head = $"3d/chara/mini/head/mchr{id}_00/clothes/pfb_mchr{id}_00_cloth00";
            paths.Add(head);
        }
        var sources = new JArray();
        foreach (string path in paths)
        {
            if (!main.AbList.TryGetValue(path, out var entry) || !File.Exists(entry.FilePath)) continue;
            var prefab = entry.Get<GameObject>();
            if (prefab == null) continue;
            foreach (var container in prefab.GetComponentsInChildren< Gallop.CySpringDataContainer >(true))
                sources.Add(new JObject { ["asset"] = path, ["data"] = JObject.Parse(JsonUtility.ToJson(container)) });
        }
        return new JObject { ["version"] = 1, ["sources"] = sources };
    }

    private IEnumerator ExportCharacter(JObject item, string folder)
    {
        var main = UmaViewerMain.Instance;
        var builder = UmaViewerBuilder.Instance;
        var id = (int?)item["character_id"] ?? 1030;
        var name = (string)item["name"] ?? "Rice Shower";
        var costume = (string)item["costume"] ?? "00";
        var character = main.Characters.FirstOrDefault(entry => entry.Id == id) ??
            new CharaEntry { Id = id, Name = name, EnName = name, ThemeColor = "#765794" };
        Logger.LogInfo("Assembling mini " + id + " outfit " + costume);
        var loading = builder.LoadUma(character, costume, true);
        while (loading.MoveNext()) yield return loading.Current;
        var container = builder.CurrentUMAContainer;
        if (container == null || container.Body == null || container.Head == null || container.Hair == null || container.UmaAnimator == null)
            throw new InvalidOperationException("The local game cache could not assemble this mini character. Download the character's game assets first.");
        yield return null;
        var animator = container.UmaAnimator;
        animator.cullingMode = AnimatorCullingMode.AlwaysAnimate;
        animator.applyRootMotion = false;
        animator.speed = 0;
        var idleName = "3d/motion/mini/event/body/chara/chr" + id + "_00/anm_min_eve_chr" + id + "_00_idle01_loop";
        var selected = item["motions"] as JArray ?? new JArray(idleName);
        var clips = selected.Select(token => main.AbList.TryGetValue((string)token, out var entry) && File.Exists(entry.FilePath)
                ? entry : throw new FileNotFoundException("Local motion unavailable: " + token)).ToList();
        if (clips.Count == 0) throw new InvalidOperationException("Select at least one animation to export.");
        var writer = new ChibiGlbWriter(container.transform);
        writer.CharacterMetadata = new JObject { ["name"] = name, ["outfit"] = (string)item["outfit"] ?? "Racing outfit",
            ["character_id"] = id, ["costume"] = costume, ["dress_id"] = item["dress_id"],
            ["region"] = (string)item["region"] ?? "global", ["name_jp"] = item["name_jp"], ["outfit_jp"] = item["outfit_jp"] };
        writer.PhysicsMetadata = ReadPhysics(item);
        File.WriteAllText(Path.Combine(folder, "physics.json"), writer.PhysicsMetadata.ToString());
        var labels = new JObject();
        foreach (var entry in clips)
        {
            Logger.LogInfo("Sampling " + entry.Name);
            var clip = entry.Get<AnimationClip>();
            if (clip == null) throw new InvalidOperationException("Could not read clip " + entry.Name);
            if (clip.length <= 0 || clip.length > 30) throw new InvalidOperationException("Motion is outside the preview's 0-30 second range: " + entry.Name);
            container.OverrideController["clip_2"] = clip;
            animator.Rebind();
            animator.speed = 0;
            animator.SetLayerWeight(0, 1);
            for (int layer = 1; layer < animator.layerCount; layer++) animator.SetLayerWeight(layer, 0);
            int frames = Math.Max(2, (int)Math.Ceiling(clip.length * 30) + 1);
            var clipName = Path.GetFileName(entry.Name);
            var samples = writer.NewSamples(frames);
            for (int frame = 0; frame < frames; frame++)
            {
                float normalized = frame / (float)(frames - 1);
                animator.Play("motion_2", 0, Math.Min(normalized, 0.999999f));
                animator.Update(0);
                writer.Sample(samples, frame);
                if (frame % 20 == 0) yield return null;
            }
            writer.AddAnimation(clipName, clip.length, samples);
            labels[clipName] = (string)item["animation_labels"]?[clipName] ?? (clipName.Contains("idle") ? "Idle" : clipName.Contains("run") ? "Run" :
                clipName.Contains("walk") ? "Walk" : clipName.Contains("win") || clipName.Contains("joy") ? "Celebrate" : clipName);
        }
        // Export geometry after sampling; node transforms are the captured starting pose.
        var filename = "model.glb";
        writer.AnimationMetadata = new JObject { ["labels"] = labels.DeepClone(), ["groups"] = item["animation_groups"]?.DeepClone() ?? new JObject() };
        writer.Save(Path.Combine(folder, filename));
        var manifest = new JObject {
            ["name"] = name, ["character_id"] = id, ["outfit"] = (string)item["outfit"] ?? "Racing outfit",
            ["costume"] = costume, ["dress_id"] = item["dress_id"], ["import_profile"] = item["import_profile"],
            ["region"] = (string)item["region"] ?? "global", ["name_jp"] = item["name_jp"], ["outfit_jp"] = item["outfit_jp"],
            ["available_in"] = item["available_in"]?.DeepClone(),
            ["animation_groups"] = item["animation_groups"]?.DeepClone() ?? new JObject(),
            ["model"] = filename, ["animation_labels"] = labels, ["faces"] = writer.Faces,
            ["source"] = "Local game assets assembled by UmaViewer; sampled at 30 fps",
        };
        File.WriteAllText(Path.Combine(folder, "manifest.json"), manifest.ToString());
        Logger.LogInfo("Export complete: " + Path.Combine(folder, filename));
    }
}
