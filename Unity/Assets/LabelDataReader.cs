using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using UnityEngine;
using Debug = UnityEngine.Debug;

public class LabelDataReader : MonoBehaviour
{
    [Header("Config")]
    [Tooltip("Path to unity_commands.json/log. " +
             "Leave empty to use <ProjectRoot>/Python/unity_commands.log")]
    public string logFilePath = "";

    [Header("Target Data")]
    [SerializeField]
    public LabelData targetLabelData;   // ScriptableObject to fill
    private string prevLabel = null;

    [SerializeField] AnimExecuter animExec;

    private void Start()
    {
        ResolveLogPathIfEmpty();
    }

    private void Update()
    {
        ReadAndApply();
    }

    // You call this from a UI Button
    public void ReadAndApply()
    {
        if (targetLabelData == null)
        {
            Debug.LogWarning("[LabelJsonReader] No LabelData ScriptableObject assigned.");
            return;
        }

        if (string.IsNullOrEmpty(logFilePath))
        {
            Debug.LogWarning("[LabelJsonReader] logFilePath is empty.");
            return;
        }

        if (!File.Exists(logFilePath))
        {
            Debug.LogWarning($"[LabelJsonReader] Log file not found at: {logFilePath}");
            return;
        }

        string json = null;
        const int maxAttempts = 3;
        for (int attempt = 1; attempt <= maxAttempts; attempt++)
        {
            try
            {
                // Allow reading while the Python bridge is writing.
                using (var fs = new FileStream(logFilePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                using (var sr = new StreamReader(fs))
                {
                    json = sr.ReadToEnd();
                }
                break;
            }
            catch (IOException)
            {
                if (attempt == maxAttempts)
                {
                    Debug.LogWarning($"[LabelJsonReader] Sharing violation reading log (path={logFilePath}).");
                    return;
                }
                Thread.Sleep(10);
            }
        }

        if (string.IsNullOrWhiteSpace(json))
        {
            Debug.LogWarning("[LabelJsonReader] Log file is empty.");
            return;
        }

            var cmd = JsonUtility.FromJson<LabelDataContainer>(json);
            if (cmd == null)
            {
                Debug.LogWarning($"[LabelJsonReader] Failed to parse JSON: {json}");
                return;
            }

            // Apply to ScriptableObject
            targetLabelData.label = cmd.label;
            targetLabelData.timestamp = cmd.timestamp;
            targetLabelData.source = cmd.source;

            if (prevLabel != cmd.label)
            {
                prevLabel = cmd.label;
                OnLabelChanged(cmd.label);
            }


            Debug.Log($"[LabelJsonReader] Updated SO -> label='{cmd.label}', source='{cmd.source}'");
        
        
    }

    private void OnLabelChanged(string newLabel)
    {
        Debug.Log("Label updated: " + newLabel);
        if(newLabel == "Walk")
        {
            CharacterAnimationController._instance.GoWalk();
        }
        if (newLabel == "Idle")
        {
            CharacterAnimationController._instance.GoIdle();
        }
        if (newLabel == "Sit")
        {
            CharacterAnimationController._instance.GoSit();
        }
        if (newLabel == "walk")
        {
            CharacterAnimationController._instance.GoWalk();
        }
        if (newLabel == "idle")
        {
            CharacterAnimationController._instance.GoIdle();
        }
        if (newLabel == "sit")
        {
            CharacterAnimationController._instance.GoSit();
        }
    }


    private void ResolveLogPathIfEmpty()
    {
        if (!string.IsNullOrEmpty(logFilePath))
        {
            logFilePath = Path.GetFullPath(logFilePath);
            return;
        }

        // Default: <ProjectRoot>/Python/unity_commands.log
        string scriptDir = Path.Combine(Application.dataPath, "../Python");
        scriptDir = Path.GetFullPath(scriptDir);
        logFilePath = Path.Combine(scriptDir, "unity_commands.log");
        logFilePath = Path.GetFullPath(logFilePath);

        Debug.Log($"[LabelJsonReader] Using log file: {logFilePath}");
    }
}

