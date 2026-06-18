using TMPro;
using UnityEngine;

public sealed class PairingUIController : MonoBehaviour
{
    public PythonBridgeLauncher pythonBridge;
    public HarBridgeLauncher harBridge;
    public TMP_InputField pairingInputField;
    public bool clearFieldAfterConnect;

    public void OnConnectButtonClicked()
    {
        HarBridgeLauncher launcher = pythonBridge != null ? pythonBridge : harBridge;

        if (launcher == null)
            launcher = FindAnyObjectByType<HarBridgeLauncher>();

        if (pythonBridge == null)
            pythonBridge = FindAnyObjectByType<PythonBridgeLauncher>();

        if (launcher == null)
        {
            Debug.LogWarning("[PairingUIController] Python bridge is missing.");
            return;
        }

        string code = pairingInputField != null ? pairingInputField.text.Trim() : "";

        if (string.IsNullOrWhiteSpace(code))
        {
            Debug.LogWarning("[PairingUIController] Pairing code is empty.");
            return;
        }

        launcher.SetPairingCode(code);
        launcher.StartBridgeIfNeeded();

        if (clearFieldAfterConnect && pairingInputField != null)
            pairingInputField.text = "";

        Debug.Log($"[PairingUIController] Bridge start requested with code: {code}");
    }
}
