using System;
using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

public sealed class HarDemoHotkeys : MonoBehaviour
{
    public HarActivityState activityState;
    public bool enableHotkeys = true;

    bool legacyInputUnavailable;

    void Start()
    {
        if (activityState == null)
            activityState = HarActivityState.Instance ?? FindAnyObjectByType<HarActivityState>();
    }

    void Update()
    {
        if (!enableHotkeys || activityState == null)
            return;

        if (WasPressed(KeyCode.Alpha0, "0"))
            Apply("idle");
        else if (WasPressed(KeyCode.Alpha1, "1"))
            Apply("walking");
        else if (WasPressed(KeyCode.Alpha2, "2"))
            Apply("crouching");
        else if (WasPressed(KeyCode.Alpha3, "3"))
            Apply("punching");
    }

    void Apply(string label)
    {
        activityState.ApplyLabel(label, DateTime.UtcNow.ToString("o"), "hotkey");
    }

    bool WasPressed(KeyCode legacyKey, string digit)
    {
#if ENABLE_INPUT_SYSTEM
        Keyboard keyboard = Keyboard.current;

        if (keyboard != null)
        {
            if (digit == "0")
                return keyboard.digit0Key.wasPressedThisFrame || keyboard.numpad0Key.wasPressedThisFrame;
            if (digit == "1")
                return keyboard.digit1Key.wasPressedThisFrame || keyboard.numpad1Key.wasPressedThisFrame;
            if (digit == "2")
                return keyboard.digit2Key.wasPressedThisFrame || keyboard.numpad2Key.wasPressedThisFrame;
            if (digit == "3")
                return keyboard.digit3Key.wasPressedThisFrame || keyboard.numpad3Key.wasPressedThisFrame;
        }
#endif

        if (legacyInputUnavailable)
            return false;

        try
        {
            return Input.GetKeyDown(legacyKey);
        }
        catch (InvalidOperationException)
        {
            legacyInputUnavailable = true;
            return false;
        }
    }
}
