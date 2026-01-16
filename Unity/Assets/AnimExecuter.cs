using UnityEngine;
using UnityEngine.AI;

public class AnimExecuter : MonoBehaviour
{
    [SerializeField] NavMeshAgent agent;
    [SerializeField] Transform normalPoint;
    [SerializeField] Transform sitPoint;
    [SerializeField] Animator animator;


    bool isSitting = false;

    bool waitingArrival = false;
    string currentLabel = "";

    public void ExecuteAnim(string label)
    {
        currentLabel = label;
        waitingArrival = true;

        if (label.Contains("sit"))
        {
            agent.SetDestination(sitPoint.position);
        }
        else
        {
            agent.SetDestination(normalPoint.position);
        }
    }

    void Update()
    {
        if (!waitingArrival) return;
        if (agent == null) return;
        if (!agent.isOnNavMesh) return;
        if (agent.pathPending) return;

        if (agent.remainingDistance <= agent.stoppingDistance &&
            agent.velocity.sqrMagnitude < 0.01f)
        {
            waitingArrival = false;
            OnArrived();
        }
    }

    void OnArrived()
    {
        if (currentLabel.Contains("sit"))
        {
            agent.updateRotation = false;
            transform.rotation = Quaternion.LookRotation(Vector3.forward, Vector3.up);
            animator.ResetTrigger("StandToSit");
            animator.SetTrigger("StandToSit");
            isSitting = true;
            animator.SetBool("Sitting", true);
        }
        else if (currentLabel.Contains("jump"))
        {
            if (!isSitting)
            {
                animator.applyRootMotion = true;
                animator.ResetTrigger("Jump");
                animator.SetTrigger("Jump");

            }
            else
            {
                animator.SetTrigger("SitToStand");
                isSitting = false;
                animator.SetBool("Sitting", false);
                animator.ResetTrigger("Jump");

                animator.SetTrigger("Jump");

            }

            agent.updateRotation = true;
        }
        else if (currentLabel.Contains("walk"))
        {
            animator.applyRootMotion = false;

            if (!isSitting)
            {
                animator.ResetTrigger("Walk");
                animator.SetTrigger("Walk");

            }
            else
            {
                animator.SetTrigger("SitToStand");
                isSitting = false;
                animator.SetBool("Sitting", false);
                animator.ResetTrigger("Walk");

                animator.SetTrigger("Walk");

            }

            agent.updateRotation = true;
        }
        else if (currentLabel.Contains("idle"))
        {
            animator.applyRootMotion = false;

            if (!isSitting)
            {
                animator.ResetTrigger("Idle");
                animator.SetTrigger("Idle");

            }
            else
            {
                animator.SetTrigger("SitToStand");
                isSitting = false;
                animator.SetBool("Sitting", false);
                animator.ResetTrigger("Idle");

                animator.SetTrigger("Idle");

            }

            agent.updateRotation = true;
        }

        Debug.Log("Agent arrived");
    }
}
