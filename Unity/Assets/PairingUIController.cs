using UnityEngine;
using TMPro;   // For TMP_InputField

public class PairingUIController : MonoBehaviour
{
    [Header("References")]
    [Tooltip("Reference to the PythonLabelBridge component in the scene.")]
    public PythonBridgeLauncher pythonBridge;

    [Tooltip("Input field where the user types the pairing code shown on the REMOTE controller.")]
    public TMP_InputField pairingInputField;

    [Header("Options")]
    [Tooltip("Start the bridge automatically as soon as a non-empty code is entered and button is pressed.")]
    public bool clearFieldAfterConnect = false;

    /// <summary>
    /// Call this from a UI Button's OnClick() event.
    /// </summary>
    public void OnConnectButtonClicked()
    {
        string code = pairingInputField.text.Trim();
        if (string.IsNullOrEmpty(code))
        {
            Debug.LogWarning("[PairingUIController] Pairing code is empty.");
            return;
        }

        pythonBridge.pairingCode = code;
        pythonBridge.StartBridgeIfNeeded();
        Debug.Log($"[PairingUIController] Bridge start requested with code: {code}");
    }
}
