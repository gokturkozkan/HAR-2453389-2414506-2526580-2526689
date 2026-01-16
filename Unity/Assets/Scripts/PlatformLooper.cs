using UnityEngine;

public class PlatformLooper : MonoBehaviour
{
    [Header("Movement")]
    [Tooltip("World direction platforms move in (usually -Z for runners).")]
    public Vector3 moveDirection = Vector3.back;

    [Tooltip("Units per second.")]
    public float speed = 8f;

    [Header("Recycling")]
    [Tooltip("All platform pieces in the order they appear (back -> front or any order; script will compute front).")]
    public Transform[] platforms;

    [Tooltip("How far after a platform goes behind this Z/X/etc it will be recycled.")]
    public float recycleBehindDistance = 30f;

    [Tooltip("Gap between platforms along the movement axis (match your platform length).")]
    public float platformLength = 20f;

    [Tooltip("Extra spacing added when placing recycled platforms.")]
    public float extraGap = 0f;

    Vector3 _dir;

    public static PlatformLooper _instance;

    void Awake()
    {
        _dir = moveDirection.normalized;
        if (_dir.sqrMagnitude < 0.0001f)
            _dir = Vector3.back;
        
        _instance = this;
    }

    void Update()
    {
        float step = speed * Time.deltaTime;

        // Move all platforms
        for (int i = 0; i < platforms.Length; i++)
        {
            platforms[i].position += _dir * step;
        }

        // Find the "frontmost" platform along the opposite of movement direction
        // If moveDirection is back (-Z), then front is +Z (which is -dir)
        Transform frontMost = platforms[0];
        float bestFrontDot = Vector3.Dot(frontMost.position, -_dir);

        for (int i = 1; i < platforms.Length; i++)
        {
            float d = Vector3.Dot(platforms[i].position, -_dir);
            if (d > bestFrontDot)
            {
                bestFrontDot = d;
                frontMost = platforms[i];
            }
        }

        // Recycle any platform that is too far "behind" along movement direction
        // "Behind" means it has moved far in _dir direction relative to origin/front reference.
        for (int i = 0; i < platforms.Length; i++)
        {
            Transform p = platforms[i];

            // How far "behind" is p along movement direction? We measure dot along +dir.
            float behindDot = Vector3.Dot(p.position, _dir);

            // Put your recycle line in front of everything by comparing to a line anchored near the manager:
            // Manager position acts like a reference point; adjust recycleBehindDistance.
            float managerBehindDot = Vector3.Dot(transform.position, _dir);

            if (behindDot > managerBehindDot + recycleBehindDistance)
            {
                // Place it after the current frontmost
                Vector3 newPos = frontMost.position + (-_dir) * (platformLength + extraGap);

                // Keep lateral/vertical alignment if you want (optional):
                // newPos.x = p.position.x; newPos.y = p.position.y;

                p.position = newPos;

                // Update frontMost to this newly placed platform
                frontMost = p;
                bestFrontDot = Vector3.Dot(frontMost.position, -_dir);
            }
        }
    }
}
