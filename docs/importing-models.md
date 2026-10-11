# Importing models

The included `models/` library is ready to use. This optional Windows workflow
adds or refreshes exports from an installed Global or JP game.

## Requirements

- Python and .NET SDK 8 or newer.
- A Global or JP game installation with the desired assets already downloaded.
- A separately supplied Windows x64 **Mono** UmaViewer build containing
  `UmaViewer_Data/Managed/umamusume.dll`.

The adapter was tested with the UmaViewer2 Mono build at `abd56e8`. IL2CPP
builds are incompatible; other versions may require an adapter update.
A Unity Editor installation is not required.

## Export the library

The importer reads the installed master, selects released race outfits,
checks local assets and their dependencies, and exports their original rigs,
textures and motions to `models/`. Alternate outfit titles come from the
trainee-card/dress mapping. Missing assets are reported; game assets are not
downloaded by the importer.

The included library uses JP models for both views. From the Chibi Studio
project folder, choose `-Region jp` and its game-data directory:

```powershell
.\tools\chibi_export\export.ps1 -Region jp -AllRaceOutfits `
  -ViewerPath 'C:\Tools\UmaViewer' `
  -GamePath 'F:\SteamLibrary\steamapps\common\UmamusumePrettyDerby_Jpn\UmamusumePrettyDerby_Jpn_Data\Persistent' `
  -TranslationsPath 'C:\Tools\translations\text_data_dict.json'
```

`-TranslationsPath` is optional. It accepts UmaTL's
[`text_data_dict.json`](https://github.com/UmaTL/hachimi-tl-en/blob/main/localized_data/text_data_dict.json)
for English character and outfit names. Existing official Global names are
preferred when available. Untranslated titles retain their Japanese text;
generic dress labels do not replace an outfit's actual title. Both languages
remain searchable.

JP exports use IDs such as `jp-1030` and `jp-1030-40` in `models/`. The browser's
Global/JP button filters this shared collection. Global shows only released
characters and outfits while using the same expanded animations and expressions.
JP imports include the available common looping mini body motions and each
character's original poses.
Scene props, camera tracks and multi-character scenes are not exported.

The importer uses `tools/chibi_export/global-outfits.json` for Global availability
and official English names. Supply `-GlobalGamePath` with a Global game-data
directory to read its current `master/master.mdb` instead. This only updates
availability and naming; the exported models still come from JP. Availability
is recorded in each manifest's `available_in` list.

The first run makes a private player copy in `.local/chibi-player`, installs
the pinned BepInEx 5.4.23.5 runtime after verifying its SHA-256, and reads
compatibility settings from pinned official UmaViewer source. Later runs
reuse these tools. The supplied viewer and original game cache are unchanged.
JP uses a separate `.local/chibi-player-jp` copy and `.local/chibi-import-jp`
reports. The original installed game data is read without modification.

```powershell
# Keep completed exports and retry missing ones.
.\tools\chibi_export\export.ps1 -Region jp -AllRaceOutfits

# Refresh cloth data without resampling the animations.
.\tools\chibi_export\export.ps1 -Region jp -AllRaceOutfits -PhysicsOnly

# Refresh cloth data for Agnes Tachyon.
.\tools\chibi_export\export.ps1 -Region jp -PhysicsOnly -CharacterId 1032

# Export Rice Shower with the four default motions.
.\tools\chibi_export\export.ps1 -Region jp -CharacterId 1030 -Name 'Rice Shower' -Outfit 'Rosy Dreams'
```

The single-character command writes that outfit's model again with the chosen
motions. Use the batch command to preserve completed full-motion exports.
Repeat `-TranslationsPath` when refreshing names to retain the community English
translations. The supplied Global roster only translates outfits released there.

## Options and output

- `-Region global` (default) or `-Region jp` selects the game's database format
  and destination IDs.
- `-GamePath` selects the game-data directory containing `meta` and
  `dat` when the game is installed elsewhere.
- `-ModelsPath` selects the destination library. Otherwise the importer uses
  `CHIBI_MODELS_DIR`, then the project's `models/` folder.
- `-Costume` and `-Outfit` select an outfit variant and its display title.
- `-Motions` accepts explicit cached motion paths.
- `-TranslationsPath` supplies optional English JP names and titles.
- `-GlobalGamePath` refreshes Global availability and official names during a JP batch import.
- `-InventoryOnly` lists available local assets.
- `-Force` rebuilds completed matching exports.

The model, manifest and `physics.json` belong in the library. Temporary export
markers are ignored by Git. Catalogs, missing assets, batch reports and physics
reports go under `.local/chibi-import/`. The player log is
`.local/chibi-player/chibi-studio-player.log`.

Each `manifest.json` identifies a self-contained GLB. For example:

```json
{
  "name": "Rice Shower",
  "region": "jp",
  "available_in": ["global", "jp"],
  "character_id": 1030,
  "costume": "00",
  "outfit": "Rosy Dreams",
  "model": "model.glb"
}
```

Full exports also provide animation labels and groups, facial presets and
cloth parameters. GLB extras store `umaCharacter`, `umaAnimations`, `umaFaces`
and `umaPhysics` so direct file imports retain these features.

The browser reads embedded cloth data from the GLB. `physics.json` preserves
the source parameters for later metadata refreshes.
