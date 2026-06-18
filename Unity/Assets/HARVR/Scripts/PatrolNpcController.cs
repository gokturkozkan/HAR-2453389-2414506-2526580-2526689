using UnityEngine;

public sealed class PatrolNpcController : MonoBehaviour
{
    [Header("Patrol")]
    public Transform[] waypoints;
    public float patrolSpeed = 1.25f;
    public float waypointTolerance = 0.18f;
    public float waitAtWaypointSeconds = 0.4f;

    [Header("Vision")]
    public HarPlayerStealth player;
    public Transform visionOrigin;
    public float visionDistance = 6.5f;
    [Range(5f, 160f)] public float visionAngle = 65f;
    public float loseSightDelay = 0.75f;

    [Header("Visuals")]
    public Renderer[] bodyRenderers;
    public bool tintBodyOnState = true;
    public Color patrolColor = new Color(0.12f, 0.22f, 0.35f, 1f);
    public Color alertColor = new Color(0.95f, 0.12f, 0.08f, 1f);
    public Color downedColor = new Color(0.18f, 0.18f, 0.18f, 1f);

    int waypointIndex;
    float waitTimer;
    float lastSeenTime = -999f;
    bool isDown;

    public bool IsDown => isDown;
    public bool IsDetected => !isDown && Time.time - lastSeenTime <= loseSightDelay;
    public string StatusText => isDown ? "NPC down" : IsDetected ? "Detected" : "Patrolling";

    void Start()
    {
        if (player == null)
            player = FindAnyObjectByType<HarPlayerStealth>();

        if (visionOrigin == null)
            visionOrigin = transform;

        if (bodyRenderers == null || bodyRenderers.Length == 0)
            bodyRenderers = GetComponentsInChildren<Renderer>();

        ApplyBodyColor(patrolColor);
    }

    void Update()
    {
        if (isDown)
            return;

        Patrol();

        if (CanSeePlayer())
            lastSeenTime = Time.time;

        ApplyBodyColor(IsDetected ? alertColor : patrolColor);
    }

    public bool IsPlayerBehind(Vector3 playerPosition)
    {
        Vector3 toPlayer = playerPosition - transform.position;
        toPlayer.y = 0f;

        if (toPlayer.sqrMagnitude < 0.001f)
            return true;

        return Vector3.Dot(transform.forward, toPlayer.normalized) < -0.2f;
    }

    public void KnockDown()
    {
        if (isDown)
            return;

        isDown = true;
        ApplyBodyColor(downedColor);

        Vector3 euler = transform.eulerAngles;
        transform.rotation = Quaternion.Euler(82f, euler.y, euler.z);

        var cone = GetComponentInChildren<NpcVisionConeRenderer>();
        if (cone != null)
            cone.SetSuppressed(true);

        Debug.Log($"[HAR] {name} knocked down.");
    }

    bool CanSeePlayer()
    {
        if (player == null || player.IsConcealed)
            return false;

        Vector3 origin = visionOrigin != null ? visionOrigin.position : transform.position + Vector3.up * 1.5f;
        Vector3 target = player.PlayerCenter;
        Vector3 toPlayer = target - origin;
        float distance = toPlayer.magnitude;

        if (distance > visionDistance)
            return false;

        Vector3 flatDirection = toPlayer;
        flatDirection.y = 0f;

        if (flatDirection.sqrMagnitude < 0.001f)
            return true;

        float angle = Vector3.Angle(transform.forward, flatDirection.normalized);
        return angle <= visionAngle * 0.5f;
    }

    void Patrol()
    {
        if (waypoints == null || waypoints.Length == 0)
            return;

        if (waitTimer > 0f)
        {
            waitTimer -= Time.deltaTime;
            return;
        }

        Transform target = waypoints[waypointIndex];
        if (target == null)
            return;

        Vector3 destination = target.position;
        destination.y = transform.position.y;
        Vector3 toDestination = destination - transform.position;

        if (toDestination.magnitude <= waypointTolerance)
        {
            waypointIndex = (waypointIndex + 1) % waypoints.Length;
            waitTimer = waitAtWaypointSeconds;
            return;
        }

        Vector3 direction = toDestination.normalized;
        transform.position += direction * patrolSpeed * Time.deltaTime;

        if (direction.sqrMagnitude > 0.001f)
            transform.rotation = Quaternion.Slerp(transform.rotation, Quaternion.LookRotation(direction, Vector3.up), 10f * Time.deltaTime);
    }

    void ApplyBodyColor(Color color)
    {
        if (!tintBodyOnState || bodyRenderers == null)
            return;

        foreach (Renderer bodyRenderer in bodyRenderers)
        {
            if (bodyRenderer == null)
                continue;

            var material = bodyRenderer.material;

            if (material.HasProperty("_BaseColor"))
                material.SetColor("_BaseColor", color);
            else if (material.HasProperty("_Color"))
                material.SetColor("_Color", color);
        }
    }
}
