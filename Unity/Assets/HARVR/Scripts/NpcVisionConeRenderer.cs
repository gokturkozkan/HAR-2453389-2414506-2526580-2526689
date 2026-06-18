using UnityEngine;

[RequireComponent(typeof(MeshFilter), typeof(MeshRenderer))]
public sealed class NpcVisionConeRenderer : MonoBehaviour
{
    public PatrolNpcController npc;
    public float distance = 6.5f;
    [Range(5f, 160f)] public float angle = 65f;
    [Range(4, 48)] public int segments = 28;
    public Color patrolColor = new Color(1f, 0f, 0f, 0.23f);
    public Color alertColor = new Color(1f, 0f, 0f, 0.42f);

    Mesh mesh;
    MeshRenderer meshRenderer;
    bool suppressed;

    void Awake()
    {
        meshRenderer = GetComponent<MeshRenderer>();
        mesh = new Mesh { name = "NPC Vision Cone" };
        GetComponent<MeshFilter>().sharedMesh = mesh;
    }

    void OnValidate()
    {
        segments = Mathf.Max(4, segments);
        RebuildMesh();
    }

    void Start()
    {
        if (npc == null)
            npc = GetComponentInParent<PatrolNpcController>();

        RebuildMesh();
    }

    void Update()
    {
        if (npc != null)
        {
            distance = npc.visionDistance;
            angle = npc.visionAngle;
        }

        if (mesh == null)
            return;

        RebuildMesh();

        if (meshRenderer != null)
        {
            meshRenderer.enabled = !suppressed;
            Color color = npc != null && npc.IsDetected ? alertColor : patrolColor;
            var material = meshRenderer.material;

            if (material.HasProperty("_BaseColor"))
                material.SetColor("_BaseColor", color);
            else if (material.HasProperty("_Color"))
                material.SetColor("_Color", color);
        }
    }

    public void SetSuppressed(bool value)
    {
        suppressed = value;

        if (meshRenderer != null)
            meshRenderer.enabled = !suppressed;
    }

    void RebuildMesh()
    {
        if (mesh == null)
            return;

        int vertexCount = segments + 2;
        var vertices = new Vector3[vertexCount];
        var triangles = new int[segments * 6];

        vertices[0] = Vector3.zero;
        float halfAngle = angle * 0.5f;

        for (int i = 0; i <= segments; i++)
        {
            float t = i / (float)segments;
            float degrees = Mathf.Lerp(-halfAngle, halfAngle, t);
            Quaternion rotation = Quaternion.Euler(0f, degrees, 0f);
            vertices[i + 1] = rotation * Vector3.forward * distance;
        }

        for (int i = 0; i < segments; i++)
        {
            int tri = i * 6;
            triangles[tri] = 0;
            triangles[tri + 1] = i + 1;
            triangles[tri + 2] = i + 2;
            triangles[tri + 3] = 0;
            triangles[tri + 4] = i + 2;
            triangles[tri + 5] = i + 1;
        }

        mesh.Clear();
        mesh.vertices = vertices;
        mesh.triangles = triangles;
        mesh.RecalculateBounds();
    }
}
