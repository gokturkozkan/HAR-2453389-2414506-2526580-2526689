using System;
using UnityEngine;

public enum HarActivityKind
{
    Unknown,
    Idle,
    Walking,
    Crouching,
    Punching
}

public sealed class HarActivityState : MonoBehaviour
{
    public static HarActivityState Instance { get; private set; }

    public event Action<HarActivityKind, string> ActivityChanged;

    [SerializeField] string currentLabel = "unknown";
    [SerializeField] string timestamp = "";
    [SerializeField] string source = "";
    [SerializeField] HarActivityKind currentActivity = HarActivityKind.Unknown;

    float lastUpdatedTime = -999f;

    public string CurrentLabel => currentLabel;
    public string Timestamp => timestamp;
    public string Source => source;
    public HarActivityKind CurrentActivity => currentActivity;
    public float SecondsSinceUpdate => Time.time - lastUpdatedTime;

    void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Debug.LogWarning("[HAR] Multiple HarActivityState instances found. Keeping the newest one.", this);
        }

        Instance = this;
    }

    public void ApplyLabel(string label, string newTimestamp, string newSource)
    {
        label = string.IsNullOrWhiteSpace(label) ? "unknown" : label.Trim();
        var normalized = Normalize(label);
        bool changed = normalized != currentActivity || !string.Equals(label, currentLabel, StringComparison.OrdinalIgnoreCase);

        currentLabel = label;
        timestamp = newTimestamp ?? "";
        source = newSource ?? "";
        currentActivity = normalized;
        lastUpdatedTime = Time.time;

        if (changed)
        {
            ActivityChanged?.Invoke(currentActivity, currentLabel);
            Debug.Log($"[HAR] Activity -> {currentActivity} from label '{currentLabel}'");
        }
    }

    public bool HasRecentActivity(HarActivityKind activity, float maxAgeSeconds)
    {
        return currentActivity == activity && SecondsSinceUpdate <= maxAgeSeconds;
    }

    public static HarActivityKind Normalize(string label)
    {
        if (string.IsNullOrWhiteSpace(label))
            return HarActivityKind.Unknown;

        string value = label.Trim().ToLowerInvariant().Replace("_", " ").Replace("-", " ");

        if (value.Contains("crouch") || value == "sit" || value == "sitting")
            return HarActivityKind.Crouching;

        if (value.Contains("punch"))
            return HarActivityKind.Punching;

        if (value.Contains("walk") || value.Contains("turning") || value == "turn")
            return HarActivityKind.Walking;

        if (value.Contains("idle") || value == "stand" || value == "standing")
            return HarActivityKind.Idle;

        return HarActivityKind.Unknown;
    }
}
