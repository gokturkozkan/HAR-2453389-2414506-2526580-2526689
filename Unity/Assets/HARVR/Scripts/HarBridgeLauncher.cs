using System;
using System.Diagnostics;
using System.IO;
using UnityEngine;
using Debug = UnityEngine.Debug;

public class HarBridgeLauncher : MonoBehaviour
{
    [Header("Bridge Process")]
    public bool autoStartBridge;
    public bool showPythonConsole = true;
    public string pythonExePath = "py";
    public string bridgeScriptPath = "";
    public string pairingCode = "";

    static Process bridgeProcess;
    string statusText = "Waiting for pairing code";

    public bool IsBridgeRunning => bridgeProcess != null && !bridgeProcess.HasExited;
    public string PairingCode => pairingCode;
    public string StatusText => IsBridgeRunning ? "Bridge running" : statusText;

    void Awake()
    {
        DontDestroyOnLoad(gameObject);
    }

    void Start()
    {
        if (autoStartBridge)
            StartBridgeIfNeeded();
    }

    void OnApplicationQuit()
    {
        StopBridge();
    }

    public void SetPairingCode(string code)
    {
        pairingCode = code == null ? "" : code.Trim();
        statusText = string.IsNullOrWhiteSpace(pairingCode) ? "Waiting for pairing code" : "Bridge stopped";
    }

    [ContextMenu("Use HARVR1 Pairing Code")]
    public void UseDefaultPairingCode()
    {
        SetPairingCode("HARVR1");
    }

    [ContextMenu("Start Bridge")]
    public void StartBridgeIfNeeded()
    {
        if (IsBridgeRunning)
        {
            statusText = "Bridge running";
            Debug.Log("[HAR] Bridge already running.");
            return;
        }

        if (string.IsNullOrWhiteSpace(pairingCode))
        {
            statusText = "Waiting for pairing code";
            Debug.LogError("[HAR] Pairing code is empty.");
            return;
        }

        string scriptPath = ResolveBridgeScriptPath();

        if (!File.Exists(scriptPath))
        {
            statusText = "Bridge error";
            Debug.LogError($"[HAR] bridge_server.py not found at: {scriptPath}");
            return;
        }

        try
        {
            var psi = new ProcessStartInfo();

            if (showPythonConsole)
            {
                psi.FileName = "cmd.exe";
                psi.Arguments = $"/K \"\"{pythonExePath}\" \"{scriptPath}\" \"{pairingCode}\"\"";
                psi.UseShellExecute = true;
                psi.CreateNoWindow = false;
            }
            else
            {
                psi.FileName = pythonExePath;
                psi.Arguments = $"\"{scriptPath}\" \"{pairingCode}\"";
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
            }

            psi.WorkingDirectory = Path.GetDirectoryName(scriptPath);
            bridgeProcess = Process.Start(psi);
            statusText = "Bridge running";

            Debug.Log($"[HAR] Python bridge started with pairing code '{pairingCode}'.");
        }
        catch (Exception ex)
        {
            statusText = "Bridge error";
            Debug.LogError($"[HAR] Failed to start bridge: {ex}");
        }
    }

    [ContextMenu("Stop Bridge")]
    public void StopBridge()
    {
        if (bridgeProcess == null)
        {
            statusText = string.IsNullOrWhiteSpace(pairingCode) ? "Waiting for pairing code" : "Bridge stopped";
            return;
        }

        try
        {
            if (!bridgeProcess.HasExited)
            {
                bridgeProcess.CloseMainWindow();

                if (!bridgeProcess.WaitForExit(1000))
                    bridgeProcess.Kill();
            }
        }
        catch (Exception ex)
        {
            Debug.LogWarning($"[HAR] Error stopping bridge: {ex.Message}");
        }
        finally
        {
            bridgeProcess = null;
            statusText = string.IsNullOrWhiteSpace(pairingCode) ? "Waiting for pairing code" : "Bridge stopped";
        }
    }

    string ResolveBridgeScriptPath()
    {
        if (!string.IsNullOrWhiteSpace(bridgeScriptPath))
            return Path.GetFullPath(bridgeScriptPath);

        string projectRoot = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
        return Path.GetFullPath(Path.Combine(projectRoot, "Python", "bridge_server.py"));
    }
}
