# Importing models

The included `models/` library is ready to use. This optional Windows workflow
adds or refreshes exports from an installed Global game.

## Requirements

- Python and .NET SDK 8 or newer.
- A Global game installation with the desired assets already downloaded.
- A separately supplied Windows x64 **Mono** UmaViewer build containing
  `UmaViewer_Data/Managed/umamusume.dll`.

The adapter was tested with the UmaViewer2 Mono build at `abd56e8`. IL2CPP
builds are incompatible; other versions may require an adapter update.
A Unity Editor installation is not required.

## Export the library

From the Chibi Studio project folder:

```powershell
.\tools\chibi_export\export.ps1 -ViewerPath 'C:\Tools\UmaViewer' -AllRaceOutfits
```

The importer reads the installed Global master, selects released race outfits,
checks local assets and their dependencies, and exports their original rigs,
textures and motions to `models/`. Alternate outfit titles come from the
trainee-card/dress mapping. Missing assets are reported; game assets are not
downloaded by the importer.

The first run makes a private player copy in `.local/chibi-player`, installs
the pinned BepInEx 5.4.23.5 runtime after verifying its SHA-256, and reads
compatibility settings from pinned official UmaViewer source. Later runs
reuse these tools. The supplied viewer and original game cache are unchanged.

```powershell
# Keep completed exports and retry missing ones.
.\tools\chibi_export\export.ps1 -AllRaceOutfits

# Refresh cloth data without resampling the animations.
.\tools\chibi_export\export.ps1 -AllRaceOutfits -PhysicsOnly

# Refresh cloth data for Agnes Tachyon.
.\tools\chibi_export\export.ps1 -PhysicsOnly -CharacterId 1032

# Export Rice Shower with the four default motions.
.\tools\chibi_export\export.ps1 -CharacterId 1030 -Name 'Rice Shower' -Outfit 'Rosy Dreams'
```

The single-character command writes that outfit's model again with the chosen
motions. Use the batch command to preserve completed full-motion exports.

## Options and output

- `-GamePath` selects the Global `Persistent` directory containing `meta` and
  `dat` when the game is installed elsewhere.
- `-ModelsPath` selects the destination library. Otherwise the importer uses
  `CHIBI_MODELS_DIR`, then the project's `models/` folder.
- `-Costume` and `-Outfit` select an outfit variant and its display title.
- `-Motions` accepts explicit cached motion paths.
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
