using System;
using UnityEngine;

public sealed class NpcHeadLookAt : MonoBehaviour
{
    public Transform target;
    public Transform head;
    public Transform neck;
    public PatrolNpcController npc;

    public float trackingDistance = 9f;
    [Range(5f, 120f)] public float maxYaw = 70f;
    [Range(0f, 70f)] public float maxPitch = 28f;
    public float turnSpeed = 8f;
    [Range(0f, 1f)] public float neckShare = 0.35f;
    public bool onlyWhenTargetVisible;

    Quaternion headRestLocalRotation;
    Quaternion neckRestLocalRotation;

    void Start()
    {
        if (npc == null)
            npc = GetComponentInParent<PatrolNpcController>();

        if (target == null)
        {
            HarPlayerStealth player = FindAnyObjectByType<HarPlayerStealth>();
            if (player != null)
                target = player.cameraTransform != null ? player.cameraTransform : player.transform;
        }

        if (head == null)
            head = FindChildByNamePart(transform, "Head");

        if (neck == null)
            neck = FindChildByNamePart(transform, "Neck");

        if (head != null)
            headRestLocalRotation = head.localRotation;

        if (neck != null)
            neckRestLocalRotation = neck.localRotation;
    }

    void LateUpdate()
    {
        if (head == null || target == null)
            return;

        bool shouldTrack = npc == null || !npc.IsDown;

        if (shouldTrack && onlyWhenTargetVisible && npc != null)
            shouldTrack = npc.IsDetected;

        Vector3 toTarget = target.position - head.position;
        if (shouldTrack && toTarget.sqrMagnitude > trackingDistance * trackingDistance)
            shouldTrack = false;

        if (!shouldTrack || toTarget.sqrMagnitude < 0.0001f)
        {
            EaseBackToRest();
            return;
        }

        Vector3 localDirection = transform.InverseTransformDirection(toTarget.normalized);
        if (localDirection.z <= 0.05f)
        {
            EaseBackToRest();
            return;
        }

        float yaw = Mathf.Atan2(localDirection.x, localDirection.z) * Mathf.Rad2Deg;
        float horizontal = new Vector2(localDirection.x, localDirection.z).magnitude;
        float pitch = Mathf.Atan2(localDirection.y, horizontal) * Mathf.Rad2Deg;

        yaw = Mathf.Clamp(yaw, -maxYaw, maxYaw);
        pitch = Mathf.Clamp(pitch, -maxPitch, maxPitch);

        float neckWeight = neck != null ? neckShare : 0f;
        float headWeight = 1f - neckWeight;
        float blend = 1f - Mathf.Exp(-turnSpeed * Time.deltaTime);

        if (neck != null)
        {
            Quaternion neckTarget = neckRestLocalRotation * Quaternion.Euler(-pitch * neckWeight, yaw * neckWeight, 0f);
            neck.localRotation = Quaternion.Slerp(neck.localRotation, neckTarget, blend);
        }

        Quaternion headTarget = headRestLocalRotation * Quaternion.Euler(-pitch * headWeight, yaw * headWeight, 0f);
        head.localRotation = Quaternion.Slerp(head.localRotation, headTarget, blend);
    }

    void EaseBackToRest()
    {
        float blend = 1f - Mathf.Exp(-turnSpeed * Time.deltaTime);

        if (neck != null)
            neck.localRotation = Quaternion.Slerp(neck.localRotation, neckRestLocalRotation, blend);

        if (head != null)
            head.localRotation = Quaternion.Slerp(head.localRotation, headRestLocalRotation, blend);
    }

    static Transform FindChildByNamePart(Transform root, string namePart)
    {
        if (root == null || string.IsNullOrWhiteSpace(namePart))
            return null;

        foreach (Transform child in root.GetComponentsInChildren<Transform>(true))
        {
            if (child.name.IndexOf(namePart, StringComparison.OrdinalIgnoreCase) >= 0)
                return child;
        }

        return null;
    }
}
