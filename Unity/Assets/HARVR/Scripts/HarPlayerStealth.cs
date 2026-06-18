using UnityEngine;

public sealed class HarPlayerStealth : MonoBehaviour
{
    public HarActivityState activityState;
    public Transform cameraTransform;
    public float bodySampleHeight = 0.35f;

    public bool IsInCover { get; private set; }
    public bool IsCrouching => activityState != null && activityState.CurrentActivity == HarActivityKind.Crouching;
    public bool IsConcealed => IsCrouching && IsInCover;

    public Vector3 PlayerCenter
    {
        get
        {
            if (cameraTransform != null)
                return cameraTransform.position;

            return transform.position + Vector3.up * bodySampleHeight;
        }
    }

    void Start()
    {
        if (activityState == null)
            activityState = HarActivityState.Instance ?? FindAnyObjectByType<HarActivityState>();

        if (cameraTransform == null && Camera.main != null)
            cameraTransform = Camera.main.transform;
    }

    void Update()
    {
        Vector3 sample = PlayerCenter;
        sample.y = transform.position.y + bodySampleHeight;
        IsInCover = HarCoverZone.AnyContains(sample);
    }
}
