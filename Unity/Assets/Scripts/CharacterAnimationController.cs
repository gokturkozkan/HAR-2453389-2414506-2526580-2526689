using System.Collections;
using UnityEngine;

public class CharacterAnimationController : MonoBehaviour
{
    private Animator animator;

    public static CharacterAnimationController _instance;

    public enum CharacterState
    {
        Idle,
        Walking,
        Sitting
    }

    private CharacterState currentState = CharacterState.Idle;
    private CharacterState targetState = CharacterState.Idle;
    private bool isTransitioning = false;

    private void Awake()
    {
        _instance = this;
    }

    void Start()
    {
        animator = GetComponent<Animator>();

        if (animator == null)
        {
            Debug.LogError("Animator component not found on " + gameObject.name);
        }
    }

    void Update()
    {
        // Check if transition animation has finished
        if (isTransitioning)
        {
            AnimatorStateInfo stateInfo = animator.GetCurrentAnimatorStateInfo(0);

            // Check if StandToSit finished (transition to Sitting happens automatically)
            if (stateInfo.IsName("Sitting"))
            {
                isTransitioning = false;
                currentState = CharacterState.Sitting;
            }
            // Check if SitToStand finished (transition to target happens automatically)
            else if (stateInfo.IsName("Idle") || stateInfo.IsName("Walking"))
            {
                isTransitioning = false;
                currentState = targetState;
            }
        }
    }

    /// <summary>
    /// Request character to go to Idle state
    /// </summary>
    [ContextMenu("Go Idle")]
    public void GoIdle()
    {
        if (currentState == CharacterState.Idle && !isTransitioning) return;

        targetState = CharacterState.Idle;
        TransitionToState(CharacterState.Idle);
    }

    /// <summary>
    /// Request character to go to Walking state
    /// </summary>
    [ContextMenu("Go Walk")]
    public void GoWalk()
    {
        if (currentState == CharacterState.Walking && !isTransitioning) return;

        targetState = CharacterState.Walking;
        TransitionToState(CharacterState.Walking);
    }

    /// <summary>
    /// Request character to go to Sitting state
    /// </summary>
    [ContextMenu("Go Sit")]
    public void GoSit()
    {
        if (currentState == CharacterState.Sitting && !isTransitioning) return;

        targetState = CharacterState.Sitting;
        TransitionToState(CharacterState.Sitting);
    }

    IEnumerator wait(float time)
    {
        yield return new WaitForSeconds(time);
        PlatformLooper._instance.speed = 1.3f;
    }

    private void TransitionToState(CharacterState newState)
    {
        // Already at target state
        if (currentState == newState && !isTransitioning)
        {
            return;
        }

        if ((int)newState == 1)
        {
            if(currentState == CharacterState.Sitting)
                StartCoroutine(wait(1.6f));
            else
                PlatformLooper._instance.speed = 1.3f;
        }
        else
        {
            PlatformLooper._instance.speed = 0;
        }

        // Currently sitting, need to stand up first
        if (currentState == CharacterState.Sitting && newState != CharacterState.Sitting)
        {
            isTransitioning = true;
            animator.SetInteger("State", (int)newState); // SitToStand
            Debug.Log("Transitioning: Sitting -> SitToStand -> " + newState);

            // Set target state AFTER one frame so SitToStand knows where to go
            StartCoroutine(SetStateAfterFrame((int)newState));
        }
        // Going to sit, need transition animation
        else if (newState == CharacterState.Sitting && currentState != CharacterState.Sitting)
        {
            isTransitioning = true;
            animator.SetInteger("State", 3); // StandToSit
            Debug.Log("Transitioning: " + currentState + " -> StandToSit -> Sitting");

            // DON'T set State = 2 here! StandToSit → Sitting uses Exit Time, not condition
            // The sitting state will be set by Update() when animation reaches Sitting
        }
        // Direct transition (Idle <-> Walking)
        else
        {
            currentState = newState;
            animator.SetInteger("State", (int)newState);
            Debug.Log("Direct transition to: " + newState);
        }
    }

    private System.Collections.IEnumerator SetStateAfterFrame(int stateValue)
    {
        
        yield return null; // Wait one frame
        animator.SetInteger("State", stateValue);
        currentState = (CharacterState)stateValue;
        Debug.Log("Set State parameter to: " + stateValue);
    }

    /// <summary>
    /// Get current character state
    /// </summary>
    public CharacterState GetCurrentState()
    {
        return currentState;
    }

    /// <summary>
    /// Check if character is currently transitioning
    /// </summary>
    public bool IsTransitioning()
    {
        return isTransitioning;
    }
}