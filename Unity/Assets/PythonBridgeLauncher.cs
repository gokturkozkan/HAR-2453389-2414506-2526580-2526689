using System;
using System.Diagnostics;
using System.IO;
using UnityEngine;
using Debug = UnityEngine.Debug;

public class PythonBridgeLauncher : MonoBehaviour
{
    [Header("Bridge Process")]
    public bool autoStartBridge = false;

    [Tooltip("If true, show cmd window (useful for debugging).")]
    public bool showPythonConsole = true;

    [Tooltip("Path to Python. On your machine this is 'py'.")]
    public string pythonExePath = "py";

    [Tooltip("Path to bridge_server.py. Leave empty for <ProjectRoot>/Python/bridge_server.py.")]
    public string bridgeScriptPath = "";

    [Tooltip("Pairing code you got from the REMOTE controller.")]
    public string pairingCode = "";

    private static Process _bridgeProcess;
    private static bool _bridgeLaunchedOnce = false;

    private void Awake()
    {
        DontDestroyOnLoad(gameObject);
    }

    private void Start()
    {
        if (autoStartBridge)
            StartBridgeIfNeeded();
    }

    private void OnApplicationQuit()
    {
        StopBridge();
    }

    public void StartBridgeIfNeeded()
    {
        if (_bridgeLaunchedOnce && _bridgeProcess != null && !_bridgeProcess.HasExited)
        {
            Debug.Log("[PythonBridge] Bridge already running.");
            return;
        }

        if (string.IsNullOrWhiteSpace(pairingCode))
        {
            Debug.LogError("[PythonBridge] Pairing code is empty.");
            return;
        }

        string scriptPath = bridgeScriptPath;
        if (string.IsNullOrEmpty(scriptPath))
        {
            scriptPath = Path.Combine(Application.dataPath, "../Python/bridge_server.py");
        }

        scriptPath = Path.GetFullPath(scriptPath);
        Debug.Log($"[PythonBridge] scriptPath = {scriptPath}");
        Debug.Log($"[PythonBridge] pythonExePath = {pythonExePath}");

        if (!File.Exists(scriptPath))
        {
            Debug.LogError($"[PythonBridge] bridge_server.py not found at: {scriptPath}");
            return;
        }

        try
        {
            var psi = new ProcessStartInfo();

            if (showPythonConsole)
            {
                // cmd /K keeps the window open so you see errors
                psi.FileName = "cmd.exe";
                psi.Arguments =
                    $"/K \"\"{pythonExePath}\" \"{scriptPath}\" \"{pairingCode}\"\"";
                psi.UseShellExecute = true;
                psi.CreateNoWindow = false;
                psi.WorkingDirectory = Path.GetDirectoryName(scriptPath);
            }
            else
            {
                psi.FileName = pythonExePath;
                psi.Arguments = $"\"{scriptPath}\" \"{pairingCode}\"";
                psi.WorkingDirectory = Path.GetDirectoryName(scriptPath);
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
            }

            _bridgeProcess = Process.Start(psi);
            _bridgeLaunchedOnce = true;

            Debug.Log("[PythonBridge] Started Python bridge with pairing code.");
        }
        catch (Exception ex)
        {
            Debug.LogError($"[PythonBridge] Failed to start bridge: {ex}");
        }
    }

    public void StopBridge()
    {
        if (_bridgeProcess == null)
            return;

        try
        {
            if (!_bridgeProcess.HasExited)
            {
                _bridgeProcess.CloseMainWindow();
                if (!_bridgeProcess.WaitForExit(1000))
                    _bridgeProcess.Kill();
            }

            Debug.Log("[PythonBridge] Bridge process stopped.");
        }
        catch (Exception ex)
        {
            Debug.LogWarning($"[PythonBridge] Error stopping bridge: {ex}");
        }
        finally
        {
            _bridgeProcess = null;
        }
    }
}
