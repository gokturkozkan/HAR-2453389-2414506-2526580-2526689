using UnityEngine;

public sealed class NpcAnimatorDriver : MonoBehaviour
{
    public PatrolNpcController npc;
    public Animator animator;
    public string speedParameter = "Speed";
    public float dampTime = 0.12f;

    Vector3 lastPosition;

    void Start()
    {
        if (npc == null)
            npc = GetComponentInParent<PatrolNpcController>();

        if (animator == null)
            animator = GetComponentInChildren<Animator>();

        if (animator != null)
            animator.applyRootMotion = false;

        Transform sample = npc != null ? npc.transform : transform;
        lastPosition = sample.position;
    }

    void Update()
    {
        if (animator == null)
            return;

        Transform sample = npc != null ? npc.transform : transform;
        float speed = Time.deltaTime > 0f ? Vector3.Distance(sample.position, lastPosition) / Time.deltaTime : 0f;
        lastPosition = sample.position;

        if (npc != null && npc.IsDown)
            speed = 0f;

        animator.SetFloat(speedParameter, speed, dampTime, Time.deltaTime);
    }
}
