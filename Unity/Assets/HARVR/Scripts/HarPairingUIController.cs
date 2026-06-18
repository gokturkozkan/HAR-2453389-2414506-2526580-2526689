using TMPro;
using UnityEngine;
using UnityEngine.UI;

public sealed class HarPairingUIController : MonoBehaviour
{
    public HarBridgeLauncher bridgeLauncher;
    public TMP_InputField pairingInputField;
    public Button connectButton;
    public TMP_Text connectButtonLabel;
    public TMP_Text statusText;
    public bool clearFieldAfterConnect;

    void Start()
    {
        if (bridgeLauncher == null)
            bridgeLauncher = FindAnyObjectByType<HarBridgeLauncher>();

        if (pairingInputField != null)
            pairingInputField.onSubmit.AddListener(_ => OnConnectButtonClicked());

        if (connectButton != null)
            connectButton.onClick.AddListener(OnConnectButtonClicked);

        RefreshStatus();
    }

    void Update()
    {
        RefreshStatus();
    }

    public void OnConnectButtonClicked()
    {
        if (bridgeLauncher == null)
        {
            SetStatus("Bridge launcher missing");
            return;
        }

        if (bridgeLauncher.IsBridgeRunning)
        {
            SetStatus("Bridge running");
            return;
        }

        string code = pairingInputField != null ? pairingInputField.text.Trim() : "";

        if (string.IsNullOrWhiteSpace(code))
        {
            SetStatus("Waiting for pairing code");

            if (pairingInputField != null)
                pairingInputField.ActivateInputField();

            return;
        }

        bridgeLauncher.SetPairingCode(code);
        bridgeLauncher.StartBridgeIfNeeded();

        if (clearFieldAfterConnect && pairingInputField != null)
            pairingInputField.text = "";

        RefreshStatus();
    }

    void RefreshStatus()
    {
        if (bridgeLauncher == null)
        {
            SetStatus("Bridge launcher missing");
            return;
        }

        bool running = bridgeLauncher.IsBridgeRunning;

        if (connectButton != null)
            connectButton.interactable = !running;

        if (connectButtonLabel != null)
            connectButtonLabel.text = running ? "Bridge Running" : "Start Server";

        string code = bridgeLauncher.PairingCode;
        string status = running
            ? "Bridge running"
            : string.IsNullOrWhiteSpace(code)
                ? "Waiting for pairing code"
                : bridgeLauncher.StatusText;

        SetStatus(status);
    }

    void SetStatus(string value)
    {
        if (statusText != null)
            statusText.text = value;
    }
}
