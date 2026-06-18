using System;
using System.IO;
using UnityEngine;

public sealed class HarActivityFileReader : MonoBehaviour
{
    [Serializable]
    sealed class HarBridgeMessage
    {
        public string label;
        public string timestamp;
        public string source;
    }

    [Header("Input")]
    public string logFilePath = "";
    public float pollIntervalSeconds = 0.2f;
    public HarActivityState activityState;

    [Header("Debug")]
    public bool logMissingFileOnce = true;

    string previousJson = "";
    float nextPollTime;
    bool missingFileLogged;

    public string ResolvedLogFilePath { get; private set; }

    void Start()
    {
        if (activityState == null)
            activityState = HarActivityState.Instance ?? FindAnyObjectByType<HarActivityState>();

        ResolvedLogFilePath = ResolveLogPath(logFilePath);
        Debug.Log($"[HAR] Activity reader using: {ResolvedLogFilePath}");
    }

    void Update()
    {
        if (Time.time < nextPollTime)
            return;

        nextPollTime = Time.time + Mathf.Max(0.05f, pollIntervalSeconds);
        ReadLatestActivity();
    }

    public void ReadLatestActivity()
    {
        if (activityState == null)
            return;

        if (string.IsNullOrWhiteSpace(ResolvedLogFilePath))
            ResolvedLogFilePath = ResolveLogPath(logFilePath);

        if (!File.Exists(ResolvedLogFilePath))
        {
            if (logMissingFileOnce && !missingFileLogged)
            {
                missingFileLogged = true;
                Debug.LogWarning($"[HAR] Activity log not found yet: {ResolvedLogFilePath}");
            }

            return;
        }

        try
        {
            string json = File.ReadAllText(ResolvedLogFilePath);

            if (string.IsNullOrWhiteSpace(json) || json == previousJson)
                return;

            previousJson = json;
            var message = JsonUtility.FromJson<HarBridgeMessage>(json);

            if (message == null || string.IsNullOrWhiteSpace(message.label))
            {
                Debug.LogWarning($"[HAR] Invalid bridge JSON: {json}");
                return;
            }

            activityState.ApplyLabel(message.label, message.timestamp, message.source);
        }
        catch (Exception ex)
        {
            Debug.LogWarning($"[HAR] Failed to read activity log: {ex.Message}");
        }
    }

    static string ResolveLogPath(string configuredPath)
    {
        if (!string.IsNullOrWhiteSpace(configuredPath))
            return Path.GetFullPath(configuredPath);

        string projectRoot = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
        return Path.GetFullPath(Path.Combine(projectRoot, "Python", "unity_commands.log"));
    }
}
