using UnityEngine;

public sealed class HarPunchTakedown : MonoBehaviour
{
    public HarActivityState activityState;
    public HarPlayerStealth player;
    public float takedownRadius = 1.65f;
    public float punchWindowSeconds = 0.45f;
    public float cooldownSeconds = 0.9f;
    public bool requireConcealedOrBehind = true;

    float nextAllowedTime;

    void Start()
    {
        if (activityState == null)
            activityState = HarActivityState.Instance ?? FindAnyObjectByType<HarActivityState>();

        if (player == null)
            player = FindAnyObjectByType<HarPlayerStealth>();
    }

    void Update()
    {
        if (activityState == null || player == null || Time.time < nextAllowedTime)
            return;

        if (!activityState.HasRecentActivity(HarActivityKind.Punching, punchWindowSeconds))
            return;

        PatrolNpcController[] npcs = FindObjectsByType<PatrolNpcController>();
        PatrolNpcController bestNpc = null;
        float bestDistance = float.MaxValue;
        Vector3 playerPosition = player.PlayerCenter;

        foreach (PatrolNpcController npc in npcs)
        {
            if (npc == null || npc.IsDown)
                continue;

            float distance = Vector3.Distance(playerPosition, npc.transform.position + Vector3.up);

            if (distance > takedownRadius || distance >= bestDistance)
                continue;

            bool allowedByStealth = !requireConcealedOrBehind || player.IsConcealed || npc.IsPlayerBehind(playerPosition);

            if (!allowedByStealth)
                continue;

            bestNpc = npc;
            bestDistance = distance;
        }

        if (bestNpc != null)
        {
            bestNpc.KnockDown();
            nextAllowedTime = Time.time + cooldownSeconds;
        }
    }
}
