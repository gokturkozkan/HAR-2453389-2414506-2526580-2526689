using System.Collections.Generic;
using UnityEngine;

[RequireComponent(typeof(Collider))]
public sealed class HarCoverZone : MonoBehaviour
{
    static readonly List<HarCoverZone> zones = new List<HarCoverZone>();

    Collider zoneCollider;

    void Awake()
    {
        zoneCollider = GetComponent<Collider>();
        zoneCollider.isTrigger = true;
    }

    void OnEnable()
    {
        if (!zones.Contains(this))
            zones.Add(this);
    }

    void OnDisable()
    {
        zones.Remove(this);
    }

    public bool Contains(Vector3 worldPoint)
    {
        if (zoneCollider == null)
            zoneCollider = GetComponent<Collider>();

        Bounds bounds = zoneCollider.bounds;
        var flattened = new Vector3(worldPoint.x, bounds.center.y, worldPoint.z);
        return bounds.Contains(flattened);
    }

    public static bool AnyContains(Vector3 worldPoint)
    {
        for (int i = zones.Count - 1; i >= 0; i--)
        {
            if (zones[i] == null)
            {
                zones.RemoveAt(i);
                continue;
            }

            if (zones[i].Contains(worldPoint))
                return true;
        }

        return false;
    }
}
