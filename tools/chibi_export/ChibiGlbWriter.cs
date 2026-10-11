// Focused glTF 2 writer: assembled mini geometry, skinning, embedded textures and sampled TRS.
// Unity's left-handed coordinates are reflected across Z; UV V is flipped for glTF images.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;

public sealed class ChibiGlbWriter
{
    private readonly Transform root;
    private readonly Transform[] transforms;
    private readonly Dictionary<Transform, int> nodeIds = new Dictionary<Transform, int>();
    private readonly Dictionary<Material, int> materialIds = new Dictionary<Material, int>();
    private readonly Dictionary<Texture, int> textureIds = new Dictionary<Texture, int>();
    private readonly MemoryStream binary = new MemoryStream();
    private readonly JArray nodes = new JArray(), meshes = new JArray(), skins = new JArray(),
        materials = new JArray(), images = new JArray(), textures = new JArray(),
        views = new JArray(), accessors = new JArray(), animations = new JArray();
    private readonly JObject faceMeshes = new JObject();
    public JObject Faces { get; private set; }
    public JObject AnimationMetadata { get; set; } = new JObject();
    public JObject PhysicsMetadata { get; set; } = new JObject();
    public JObject CharacterMetadata { get; set; } = new JObject();

    public ChibiGlbWriter(Transform root)
    {
        this.root = root;
        transforms = root.GetComponentsInChildren<Transform>(true);
        for (int i = 0; i < transforms.Length; i++) nodeIds.Add(transforms[i], i);
        foreach (var transform in transforms)
        {
            var node = new JObject { ["name"] = transform.name,
                ["translation"] = Values(Position(transform)), ["rotation"] = Values(Rotation(transform)),
                ["scale"] = Values(Scale(transform)) };
            var children = new JArray();
            foreach (Transform child in transform) if (nodeIds.ContainsKey(child)) children.Add(nodeIds[child]);
            if (children.Count > 0) node["children"] = children;
            nodes.Add(node);
        }
    }

    public float[][] NewSamples(int count) => transforms.Select(_ => new float[count * 10]).ToArray();

    public void Sample(float[][] samples, int frame)
    {
        for (int i = 0; i < transforms.Length; i++)
        {
            var values = Position(transforms[i]).Concat(Rotation(transforms[i])).Concat(Scale(transforms[i])).ToArray();
            Array.Copy(values, 0, samples[i], frame * 10, 10);
        }
    }

    public void AddAnimation(string name, float duration, float[][] samples)
    {
        int count = samples[0].Length / 10;
        int times = Floats(Enumerable.Range(0, count).Select(i => duration * i / (count - 1)).ToArray(), 1, "SCALAR", true);
        var channels = new JArray();
        var samplers = new JArray();
        for (int node = 0; node < transforms.Length; node++)
        {
            // glTF skinning is driven by joints, never by the renderer's own TRS.
            if (transforms[node].GetComponent<SkinnedMeshRenderer>() != null) continue;
            for (int part = 0; part < 3; part++)
            {
                int offset = part == 0 ? 0 : part == 1 ? 3 : 7;
                int width = part == 1 ? 4 : 3;
                string path = part == 0 ? "translation" : part == 1 ? "rotation" : "scale";
                var values = new float[count * width];
                bool changing = false;
                for (int frame = 0; frame < count; frame++)
                    for (int component = 0; component < width; component++)
                    {
                        float value = samples[node][frame * 10 + offset + component];
                        values[frame * width + component] = value;
                        if (Math.Abs(value - samples[node][offset + component]) > 0.000001f) changing = true;
                    }
                // Include constant tracks too: changing clips must restore the whole recorded pose.
                float[] track = changing ? values : values.Take(width).Concat(values.Take(width)).ToArray();
                int input = changing ? times : Floats(new[] { 0f, duration }, 1, "SCALAR", true);
                int output = Floats(track, width, part == 1 ? "VEC4" : "VEC3");
                int sampler = samplers.Count;
                samplers.Add(new JObject { ["input"] = input, ["output"] = output, ["interpolation"] = "LINEAR" });
                channels.Add(new JObject { ["sampler"] = sampler, ["target"] = new JObject { ["node"] = node, ["path"] = path } });
            }
        }
        animations.Add(new JObject { ["name"] = name, ["channels"] = channels, ["samplers"] = samplers });
    }

    private static float[] Position(Transform t) => new[] { t.localPosition.x, t.localPosition.y, -t.localPosition.z };
    private static float[] Rotation(Transform t) => new[] { -t.localRotation.x, -t.localRotation.y, t.localRotation.z, t.localRotation.w };
    private static float[] Scale(Transform t) => new[] { t.localScale.x, t.localScale.y, t.localScale.z };
    private static JArray Values(IEnumerable<float> numbers) => new JArray(numbers.Select(number => (JToken)new JValue(number)));
    private void Align() { while (binary.Length % 4 != 0) binary.WriteByte(0); }

    private int View(byte[] bytes)
    {
        Align();
        int offset = (int)binary.Length;
        binary.Write(bytes, 0, bytes.Length);
        views.Add(new JObject { ["buffer"] = 0, ["byteOffset"] = offset, ["byteLength"] = bytes.Length });
        return views.Count - 1;
    }

    private int Floats(float[] values, int width, string type, bool bounds = false)
    {
        var bytes = new byte[values.Length * 4];
        Buffer.BlockCopy(values, 0, bytes, 0, bytes.Length);
        var accessor = new JObject { ["bufferView"] = View(bytes), ["componentType"] = 5126,
            ["count"] = values.Length / width, ["type"] = type };
        if (bounds)
        {
            var low = Enumerable.Repeat(float.PositiveInfinity, width).ToArray();
            var high = Enumerable.Repeat(float.NegativeInfinity, width).ToArray();
            for (int i = 0; i < values.Length; i++) { low[i % width] = Math.Min(low[i % width], values[i]); high[i % width] = Math.Max(high[i % width], values[i]); }
            accessor["min"] = Values(low); accessor["max"] = Values(high);
        }
        accessors.Add(accessor);
        return accessors.Count - 1;
    }

    private int Integers(Array values, int bytesPerValue, int width, string type, int componentType)
    {
        var bytes = new byte[values.Length * bytesPerValue];
        Buffer.BlockCopy(values, 0, bytes, 0, bytes.Length);
        accessors.Add(new JObject { ["bufferView"] = View(bytes), ["componentType"] = componentType,
            ["count"] = values.Length / width, ["type"] = type });
        return accessors.Count - 1;
    }

    private int TextureId(Texture texture)
    {
        if (textureIds.TryGetValue(texture, out var existing)) return existing;
        var target = RenderTexture.GetTemporary(texture.width, texture.height, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
        var previous = RenderTexture.active;
        var previousSrgb = GL.sRGBWrite;
        Texture2D readable = null;
        byte[] png;
        try
        {
            GL.sRGBWrite = true;
            Graphics.Blit(texture, target);
            RenderTexture.active = target;
            readable = new Texture2D(texture.width, texture.height, TextureFormat.RGBA32, false, false);
            readable.ReadPixels(new Rect(0, 0, texture.width, texture.height), 0, 0);
            readable.Apply();
            png = readable.EncodeToPNG();
        }
        finally
        {
            RenderTexture.active = previous;
            GL.sRGBWrite = previousSrgb;
            RenderTexture.ReleaseTemporary(target);
            if (readable != null) UnityEngine.Object.Destroy(readable);
        }
        images.Add(new JObject { ["name"] = texture.name, ["mimeType"] = "image/png", ["bufferView"] = View(png) });
        textures.Add(new JObject { ["source"] = images.Count - 1, ["sampler"] = 0 });
        int id = textures.Count - 1;
        textureIds.Add(texture, id);
        return id;
    }

    private int MaterialId(Material material, string meshName)
    {
        if (materialIds.TryGetValue(material, out var existing)) return existing;
        var pbr = new JObject { ["baseColorFactor"] = new JArray(1, 1, 1, 1), ["metallicFactor"] = 0, ["roughnessFactor"] = 1 };
        var texture = material.HasProperty("_MainTex") ? material.GetTexture("_MainTex") : material.mainTexture;
        if (meshName == "M_Cheek")
        {
            var tint = material.HasProperty("_Color") ? material.GetColor("_Color").linear : Color.white;
            pbr["baseColorFactor"] = new JArray(tint.r, tint.g, tint.b, tint.a);
        }
        if (texture != null) pbr["baseColorTexture"] = new JObject { ["index"] = TextureId(texture) };
        var data = new JObject { ["name"] = material.name, ["pbrMetallicRoughness"] = pbr,
            ["doubleSided"] = true, ["extensions"] = new JObject { ["KHR_materials_unlit"] = new JObject() } };
        bool decal = meshName == "M_Eye" || meshName == "M_Mouth" || meshName == "M_Cheek" || meshName.StartsWith("M_Mayu");
        data["alphaMode"] = decal ? "BLEND" : "MASK";
        if (!decal) data["alphaCutoff"] = 0.3f;
        materials.Add(data);
        int id = materials.Count - 1;
        materialIds.Add(material, id);
        return id;
    }

    private void Geometry()
    {
        foreach (var renderer in root.GetComponentsInChildren<Renderer>())
        {
            if (!renderer.enabled || !renderer.gameObject.activeInHierarchy) continue;
            var skinned = renderer as SkinnedMeshRenderer;
            var filter = renderer.GetComponent<MeshFilter>();
            var mesh = skinned != null ? skinned.sharedMesh : filter != null ? filter.sharedMesh : null;
            if (mesh == null || mesh.vertexCount == 0) continue;
            if (!mesh.isReadable) throw new InvalidOperationException("Mesh is not readable: " + mesh.name);
            var attributes = new JObject {
                ["POSITION"] = Floats(mesh.vertices.SelectMany(v => new[] { v.x, v.y, -v.z }).ToArray(), 3, "VEC3", true),
            };
            if (mesh.normals.Length == mesh.vertexCount) attributes["NORMAL"] = Floats(mesh.normals.SelectMany(v => new[] { v.x, v.y, -v.z }).ToArray(), 3, "VEC3");
            if (mesh.uv.Length == mesh.vertexCount) attributes["TEXCOORD_0"] = Floats(mesh.uv.SelectMany(v => new[] { v.x, 1 - v.y }).ToArray(), 2, "VEC2");
            int? skinIndex = null;
            if (skinned != null && skinned.bones.Length > 0)
            {
                var joints = new List<ushort>();
                var weights = new List<float>();
                foreach (var weight in mesh.boneWeights)
                {
                    joints.AddRange(new[] { (ushort)weight.boneIndex0, (ushort)weight.boneIndex1, (ushort)weight.boneIndex2, (ushort)weight.boneIndex3 });
                    weights.AddRange(new[] { weight.weight0, weight.weight1, weight.weight2, weight.weight3 });
                }
                if (weights.Count != mesh.vertexCount * 4) throw new InvalidOperationException("Unexpected skin weights in " + mesh.name);
                attributes["JOINTS_0"] = Integers(joints.ToArray(), 2, 4, "VEC4", 5123);
                attributes["WEIGHTS_0"] = Floats(weights.ToArray(), 4, "VEC4");
                var inverseBinds = new List<float>();
                var flip = Matrix4x4.Scale(new Vector3(1, 1, -1));
                foreach (var bind in mesh.bindposes)
                {
                    var matrix = flip * bind * flip;
                    for (int column = 0; column < 4; column++) for (int row = 0; row < 4; row++) inverseBinds.Add(matrix[row, column]);
                }
                skins.Add(new JObject { ["inverseBindMatrices"] = Floats(inverseBinds.ToArray(), 16, "MAT4"),
                    ["joints"] = new JArray(skinned.bones.Select(bone => nodeIds[bone])) });
                skinIndex = skins.Count - 1;
            }
            foreach (var attribute in attributes.Properties())
                views[(int)accessors[(int)attribute.Value]["bufferView"]]["target"] = 34962;
            var primitives = new JArray();
            for (int submesh = 0; submesh < mesh.subMeshCount; submesh++)
            {
                var indices = mesh.GetTriangles(submesh);
                if (indices.Length == 0) continue;
                for (int i = 0; i < indices.Length; i += 3) { int swap = indices[i]; indices[i] = indices[i + 2]; indices[i + 2] = swap; }
                var material = renderer.sharedMaterials[Math.Min(submesh, renderer.sharedMaterials.Length - 1)];
                int indexAccessor = Integers(indices, 4, 1, "SCALAR", 5125);
                views[(int)accessors[indexAccessor]["bufferView"]]["target"] = 34963;
                primitives.Add(new JObject { ["attributes"] = attributes.DeepClone(), ["mode"] = 4,
                    ["indices"] = indexAccessor, ["material"] = MaterialId(material, renderer.name) });
            }
            meshes.Add(new JObject { ["name"] = mesh.name, ["primitives"] = primitives });
            var node = (JObject)nodes[nodeIds[renderer.transform]];
            node["mesh"] = meshes.Count - 1;
            if (skinIndex.HasValue) node["skin"] = skinIndex.Value;
            string part = renderer.name == "M_Eye" ? "eyes" : renderer.name == "M_Mouth" ? "mouth" : renderer.name.StartsWith("M_Mayu") ? "brows" : null;
            if (part != null) faceMeshes[renderer.name] = new JObject { ["part"] = part, ["columns"] = 4, ["rows"] = part == "brows" ? 4 : 8, ["flip_v"] = true };
        }
        if (meshes.Count == 0) throw new InvalidOperationException("No character meshes were assembled.");
        using (var source = typeof(ChibiGlbWriter).Assembly.GetManifestResourceStream("chibi-face-presets.json"))
        using (var reader = new StreamReader(source)) Faces = JObject.Parse(reader.ReadToEnd());
        Faces["meshes"] = faceMeshes;
    }

    public void Save(string path)
    {
        Geometry();
        Align();
        // Face +Z in browser viewers. Keep this outside all sampled animation tracks.
        int sceneRoot = nodes.Count;
        nodes.Add(new JObject { ["name"] = "Chibi", ["rotation"] = new JArray(0, 1, 0, 0), ["children"] = new JArray(0) });
        var sceneNodes = new JArray(sceneRoot);
        // Skin nodes belong directly to the scene; their joints carry the character transform.
        for (int i = 0; i < sceneRoot; i++)
        {
            if (nodes[i]["skin"] == null) continue;
            // The joint matrices already include the renderer transform. Even tiny
            // Unity rounding offsets here are redundant in glTF's skinning model.
            ((JObject)nodes[i]).Remove("translation");
            ((JObject)nodes[i]).Remove("rotation");
            ((JObject)nodes[i]).Remove("scale");
            foreach (var node in nodes)
                if (node["children"] is JArray children)
                    foreach (var child in children.Where(child => (int)child == i).ToArray()) child.Remove();
            sceneNodes.Add(i);
        }
        var document = new JObject {
            ["asset"] = new JObject { ["version"] = "2.0", ["generator"] = "Chibi Studio exporter 0.1" },
            ["scene"] = 0, ["scenes"] = new JArray(new JObject { ["nodes"] = sceneNodes }),
            ["nodes"] = nodes, ["meshes"] = meshes, ["skins"] = skins, ["materials"] = materials,
            ["images"] = images, ["textures"] = textures, ["animations"] = animations,
            ["samplers"] = new JArray(new JObject { ["magFilter"] = 9729, ["minFilter"] = 9987, ["wrapS"] = 10497, ["wrapT"] = 10497 }),
            ["buffers"] = new JArray(new JObject { ["byteLength"] = binary.Length }),
            ["bufferViews"] = views, ["accessors"] = accessors,
            ["extensionsUsed"] = new JArray("KHR_materials_unlit"), ["extras"] = new JObject { ["umaFaces"] = Faces, ["umaAnimations"] = AnimationMetadata, ["umaPhysics"] = PhysicsMetadata, ["umaCharacter"] = CharacterMetadata },
        };
        byte[] json = Encoding.UTF8.GetBytes(document.ToString(Formatting.None));
        int jsonLength = (json.Length + 3) & ~3;
        string temporary = path + ".tmp";
        using (var file = new BinaryWriter(File.Create(temporary)))
        {
            file.Write(0x46546c67); file.Write(2); file.Write(12 + 8 + jsonLength + 8 + (int)binary.Length);
            file.Write(jsonLength); file.Write(0x4e4f534a); file.Write(json);
            for (int i = json.Length; i < jsonLength; i++) file.Write((byte)0x20);
            file.Write((int)binary.Length); file.Write(0x004e4942); file.Write(binary.ToArray());
        }
        if (File.Exists(path)) File.Replace(temporary, path, null);
        else File.Move(temporary, path);
    }
}
