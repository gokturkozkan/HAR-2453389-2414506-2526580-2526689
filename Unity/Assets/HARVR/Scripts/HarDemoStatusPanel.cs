using System.Linq;
using TMPro;
using UnityEngine;

public sealed class HarDemoStatusPanel : MonoBehaviour
{
    public TMP_Text statusText;
    public HarBridgeLauncher bridgeLauncher;
    public HarActivityState activityState;
    public HarPlayerStealth playerStealth;
    public float refreshIntervalSeconds = 0.1f;

    float nextRefreshTime;

    void Start()
    {
        if (statusText == null)
            statusText = GetComponent<TMP_Text>();

        if (bridgeLauncher == null)
            bridgeLauncher = FindAnyObjectByType<HarBridgeLauncher>();

        if (activityState == null)
            activityState = HarActivityState.Instance ?? FindAnyObjectByType<HarActivityState>();

        if (playerStealth == null)
            playerStealth = FindAnyObjectByType<HarPlayerStealth>();
    }

    void Update()
    {
        if (statusText == null || Time.time < nextRefreshTime)
            return;

        nextRefreshTime = Time.time + refreshIntervalSeconds;
        Refresh();
    }

    void Refresh()
    {
        PatrolNpcController[] npcs = FindObjectsByType<PatrolNpcController>();
        bool detected = npcs.Any(npc => npc != null && npc.IsDetected);
        int downCount = npcs.Count(npc => npc != null && npc.IsDown);

        string bridge = bridgeLauncher != null ? bridgeLauncher.StatusText : "Waiting for pairing code";
        string pairing = bridgeLauncher != null ? bridgeLauncher.PairingCode : "HARVR1";
        string activity = activityState != null ? activityState.CurrentActivity.ToString() : "Unknown";
        string label = activityState != null ? activityState.CurrentLabel : "unknown";
        string source = activityState != null ? activityState.Source : "";
        string hidden = playerStealth != null && playerStealth.IsConcealed ? "YES" : "NO";

        statusText.text =
            "HARVR STEALTH DEMO\n" +
            $"Bridge: {bridge}\n" +
            $"Pairing code: {pairing}\n" +
            $"Last activity: {activity} ({label}) {source}\n" +
            $"Hidden in cover: {hidden}\n" +
            $"Detected: {(detected ? "YES" : "NO")}\n" +
            $"NPC down: {downCount}/{npcs.Length}\n" +
            "Hotkeys: 1 Walk  2 Crouch  3 Punch  0 Idle";
    }
}
