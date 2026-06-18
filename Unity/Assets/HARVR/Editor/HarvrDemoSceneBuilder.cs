using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using TMPro;
using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;
using UnityEngine.UI;
using Object = UnityEngine.Object;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem.UI;
#endif

public static class HarvrDemoSceneBuilder
{
    const string BasicScenePath = "Assets/Scenes/BasicScene.unity";
    const string PolygonTownDemoScenePath = "Assets/PolygonTown/Scenes/Demo.unity";
    const string DemoScenePath = "Assets/Scenes/HARVRStealthDemo.unity";
    const string MaterialFolder = "Assets/HARVR/Materials";
    const string AnimationFolder = "Assets/HARVR/Animations";
    const string NpcAnimatorControllerPath = "Assets/HARVR/Animations/HARVR_NPC_Patrol.controller";
    const string NpcIdleClipPath = "Assets/Synty/AnimationBaseLocomotion/Animations/Polygon/Masculine/Idle/A_Idle_Standing_Masc.fbx";
    const string NpcWalkClipPath = "Assets/Synty/AnimationBaseLocomotion/Animations/Polygon/Masculine/Locomotion/Walk/A_Walk_FwdStrafeF_Masc.fbx";
    const string TallGrassCoverPrefabPath = "Assets/PolygonTown/Prefabs/Generic/SM_Gerneric_Grass_Patch_02.prefab";

    static readonly string[] NpcCharacterPrefabs =
    {
        "Assets/POLYGONCityCharacters/Prefabs/Character_Roadworker_01.prefab",
        "Assets/POLYGONCityCharacters/Prefabs/Character_FireFighter_01.prefab",
        "Assets/POLYGONCityCharacters/Prefabs/Character_Gangster_01.prefab",
    };

    [MenuItem("HARVR/Build Demo Scene")]
    public static void BuildDemoScene()
    {
        if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
            return;

        BuildInternal();
    }

    public static void BuildDemoSceneBatch()
    {
        BuildInternal();
    }

    static void BuildInternal()
    {
        EnsureAssetFolder("Assets/HARVR");
        EnsureAssetFolder(MaterialFolder);
        EnsureAssetFolder(AnimationFolder);

        if (File.Exists(PolygonTownDemoScenePath))
            EditorSceneManager.OpenScene(PolygonTownDemoScenePath, OpenSceneMode.Single);
        else if (File.Exists(BasicScenePath))
            EditorSceneManager.OpenScene(BasicScenePath, OpenSceneMode.Single);
        else
            EditorSceneManager.NewScene(NewSceneSetup.DefaultGameObjects, NewSceneMode.Single);

        Scene scene = SceneManager.GetActiveScene();
        GameObject existingRoot = GameObject.Find("HARVR Demo Root");

        if (existingRoot != null)
            Object.DestroyImmediate(existingRoot);

        Material groundMaterial = GetOrCreateMaterial($"{MaterialFolder}/HARVR_Ground.mat", new Color(0.12f, 0.24f, 0.14f, 1f), false);
        Material roadMaterial = GetOrCreateMaterial($"{MaterialFolder}/HARVR_Road.mat", new Color(0.09f, 0.09f, 0.1f, 1f), false);
        Material bushMaterial = GetOrCreateMaterial($"{MaterialFolder}/HARVR_Bush.mat", new Color(0.05f, 0.32f, 0.11f, 1f), false);
        Material npcMaterial = GetOrCreateMaterial($"{MaterialFolder}/HARVR_NPC.mat", new Color(0.12f, 0.22f, 0.35f, 1f), false);
        Material coneMaterial = GetOrCreateMaterial($"{MaterialFolder}/HARVR_RedVisionCone.mat", new Color(1f, 0f, 0f, 0.28f), true);
        Material panelMaterial = GetOrCreateMaterial($"{MaterialFolder}/HARVR_Panel.mat", new Color(0.02f, 0.025f, 0.03f, 0.88f), false);
        Material waypointMaterial = GetOrCreateMaterial($"{MaterialFolder}/HARVR_Waypoint.mat", new Color(1f, 0.82f, 0.18f, 1f), false);
        RuntimeAnimatorController npcAnimatorController = GetOrCreateNpcAnimatorController();

        GameObject root = new GameObject("HARVR Demo Root");
        MoveToScene(root, scene);

        BuildEnvironment(root.transform, groundMaterial, roadMaterial, bushMaterial);

        GameObject manager = new GameObject("HARVR Demo Manager");
        manager.transform.SetParent(root.transform);
        HarActivityState activityState = GetOrAdd<HarActivityState>(manager);

        HarBridgeLauncher bridgeLauncher = GetOrAdd<HarBridgeLauncher>(manager);
        bridgeLauncher.SetPairingCode("");
        bridgeLauncher.autoStartBridge = false;
        bridgeLauncher.showPythonConsole = true;

        HarActivityFileReader reader = GetOrAdd<HarActivityFileReader>(manager);
        reader.activityState = activityState;

        HarDemoHotkeys hotkeys = GetOrAdd<HarDemoHotkeys>(manager);
        hotkeys.activityState = activityState;

        GameObject playerObject = FindXrOriginOrCreateFallback();
        playerObject.transform.position = new Vector3(45f, 0f, -3.4f);

        HarPlayerStealth playerStealth = GetOrAdd<HarPlayerStealth>(playerObject);
        playerStealth.activityState = activityState;
        playerStealth.cameraTransform = FindMainCameraTransform(playerObject.transform);
        DisableExtraSceneCameras(playerStealth.cameraTransform);

        HarPunchTakedown takedown = GetOrAdd<HarPunchTakedown>(manager);
        takedown.activityState = activityState;
        takedown.player = playerStealth;
        takedown.takedownRadius = 1.75f;
        takedown.requireConcealedOrBehind = true;

        var npcs = new List<PatrolNpcController>
        {
            CreateNpc("NPC Patrol 1", root.transform, playerStealth, NpcCharacterPrefabs[0], npcAnimatorController, npcMaterial, coneMaterial, waypointMaterial,
                new[] { new Vector3(36.5f, 0f, -7.5f), new Vector3(54.5f, 0f, -7.5f) }, 1.15f),
            CreateNpc("NPC Patrol 2", root.transform, playerStealth, NpcCharacterPrefabs[1], npcAnimatorController, npcMaterial, coneMaterial, waypointMaterial,
                new[] { new Vector3(54.5f, 0f, -12.5f), new Vector3(36.5f, 0f, -12.5f) }, 1.05f),
            CreateNpc("NPC Patrol 3", root.transform, playerStealth, NpcCharacterPrefabs[2], npcAnimatorController, npcMaterial, coneMaterial, waypointMaterial,
                new[] { new Vector3(42.5f, 0f, -5.4f), new Vector3(42.5f, 0f, -15.2f), new Vector3(49.5f, 0f, -15.2f) }, 0.95f),
        };

        BuildStatusPanel(root.transform, bridgeLauncher, activityState, playerStealth, panelMaterial);
        BuildPairingPanel(root.transform, bridgeLauncher);
        EnsureEventSystem();
        ConfigureLighting();
        AddSceneToBuildSettings(DemoScenePath);

        EditorSceneManager.SaveScene(scene, DemoScenePath);
        AssetDatabase.SaveAssets();
        Selection.activeObject = AssetDatabase.LoadAssetAtPath<SceneAsset>(DemoScenePath);

        Debug.Log($"[HARVR] Demo scene built at {DemoScenePath} with {npcs.Count} Synty NPCs.");
    }

    static void BuildEnvironment(Transform root, Material groundMaterial, Material roadMaterial, Material bushMaterial)
    {
        GameObject overlayRoot = new GameObject("HARVR Gameplay Overlay - PolygonTown Demo");
        overlayRoot.transform.SetParent(root);

        CreateCoverTrigger("Gas Station Sign Cover Trigger", overlayRoot.transform, new Vector3(42.3f, 0.65f, -5.35f), new Vector3(2.7f, 1.35f, 1.8f));
        CreateCoverTrigger("Shop Front Cover Trigger", overlayRoot.transform, new Vector3(35.6f, 0.65f, -15.65f), new Vector3(2.9f, 1.35f, 1.8f));
        CreateCoverTrigger("Roadside Shrub Cover Trigger", overlayRoot.transform, new Vector3(53.1f, 0.65f, -5.35f), new Vector3(2.5f, 1.35f, 1.8f));

        CreatePrimitive(PrimitiveType.Cube, "HARVR Start Marker", overlayRoot.transform, new Vector3(45f, 0.035f, -3.75f), new Vector3(1.45f, 0.035f, 0.12f), roadMaterial);
    }

    static void BuildStreet(Transform parent, Material roadMaterial)
    {
        string road = "Assets/PolygonTown/Prefabs/Environment/SM_Env_Road_01.prefab";
        string crossing = "Assets/PolygonTown/Prefabs/Environment/SM_Env_Road_Crossing_01.prefab";
        string sidewalk = "Assets/PolygonTown/Prefabs/Environment/SM_Env_Sidewalk_Straight_01.prefab";
        string speedBump = "Assets/PolygonTown/Prefabs/Environment/SM_Env_Road_SpeedBump_01.prefab";

        float[] zPositions = { -8f, -4f, 0f, 4f, 8f, 12f };
        foreach (float z in zPositions)
        {
            string roadPath = Mathf.Abs(z) < 0.01f ? crossing : road;
            CreatePrefabOrPrimitive(roadPath, $"Synty Road Tile {z:0}", parent, new Vector3(0f, 0f, z), Quaternion.identity, Vector3.one,
                PrimitiveType.Cube, new Vector3(3.6f, 0.08f, 4f), roadMaterial);

            InstantiatePrefabIfAvailable(sidewalk, $"Left Sidewalk {z:0}", parent, new Vector3(-2.7f, 0f, z), Quaternion.identity, Vector3.one);
            InstantiatePrefabIfAvailable(sidewalk, $"Right Sidewalk {z:0}", parent, new Vector3(2.7f, 0f, z), Quaternion.Euler(0f, 180f, 0f), Vector3.one);
        }

        InstantiatePrefabIfAvailable(speedBump, "Synty Speed Bump Near", parent, new Vector3(0f, 0.02f, -1.2f), Quaternion.identity, Vector3.one);
        InstantiatePrefabIfAvailable(speedBump, "Synty Speed Bump Far", parent, new Vector3(0f, 0.02f, 7.4f), Quaternion.identity, Vector3.one);
    }

    static void BuildBuildings(Transform parent)
    {
        PlacePrefab("Left House 01", "Assets/PolygonTown/Prefabs/Buildings/Presets/SM_Bld_House_Preset_01.prefab", parent, new Vector3(-7.4f, 0f, -6.1f), 90f);
        PlacePrefab("Left Shop 01", "Assets/PolygonTown/Prefabs/Buildings/SM_Bld_Shop_01.prefab", parent, new Vector3(-7.4f, 0f, 0.2f), 90f);
        PlacePrefab("Left House 02", "Assets/PolygonTown/Prefabs/Buildings/Presets/SM_Bld_House_Preset_06.prefab", parent, new Vector3(-7.4f, 0f, 6.8f), 90f);

        PlacePrefab("Right House 01", "Assets/PolygonTown/Prefabs/Buildings/Presets/SM_Bld_House_Preset_03.prefab", parent, new Vector3(7.4f, 0f, -5.2f), -90f);
        PlacePrefab("Right Shop 01", "Assets/PolygonTown/Prefabs/Buildings/SM_Bld_Shop_03.prefab", parent, new Vector3(7.4f, 0f, 1.4f), -90f);
        PlacePrefab("Right House 02", "Assets/PolygonTown/Prefabs/Buildings/Presets/SM_Bld_House_Preset_09.prefab", parent, new Vector3(7.4f, 0f, 7.9f), -90f);
    }

    static void BuildStreetProps(Transform parent)
    {
        string streetlamp = "Assets/PolygonTown/Prefabs/Props/SM_Prop_Streetlamp_01.prefab";
        string bench = "Assets/PolygonTown/Prefabs/Props/SM_Prop_ParkBench_01.prefab";
        string stopSign = "Assets/PolygonTown/Prefabs/Props/SM_Prop_Sign_Stop_01.prefab";
        string pickup = "Assets/PolygonTown/Prefabs/Vehicles/SM_Veh_Pickup_01.prefab";
        string deliveryTruck = "Assets/PolygonTown/Prefabs/Vehicles/SM_Veh_Truck_Delivery_01.prefab";
        string tree = "Assets/PolygonTown/Prefabs/Generic/SM_Generic_Tree_02.prefab";
        string rocks = "Assets/PolygonTown/Prefabs/Generic/SM_Generic_Small_Rocks_01.prefab";

        float[] lampZ = { -6.8f, -1.8f, 3.7f, 9.1f };
        foreach (float z in lampZ)
        {
            InstantiatePrefabIfAvailable(streetlamp, $"Left Streetlamp {z:0.0}", parent, new Vector3(-3.35f, 0f, z), Quaternion.Euler(0f, 90f, 0f), Vector3.one);
            InstantiatePrefabIfAvailable(streetlamp, $"Right Streetlamp {z:0.0}", parent, new Vector3(3.35f, 0f, z + 1.8f), Quaternion.Euler(0f, -90f, 0f), Vector3.one);
        }

        InstantiatePrefabIfAvailable(bench, "Bus Stop Bench", parent, new Vector3(3.85f, 0f, -2.8f), Quaternion.Euler(0f, -90f, 0f), Vector3.one);
        InstantiatePrefabIfAvailable(stopSign, "Stop Sign", parent, new Vector3(-3.35f, 0f, -4.1f), Quaternion.Euler(0f, 90f, 0f), Vector3.one);
        InstantiatePrefabIfAvailable(pickup, "Parked Pickup", parent, new Vector3(1.2f, 0f, 5.35f), Quaternion.Euler(0f, 180f, 0f), Vector3.one * 0.95f);
        InstantiatePrefabIfAvailable(deliveryTruck, "Parked Delivery Truck", parent, new Vector3(-1.15f, 0f, -5.4f), Quaternion.identity, Vector3.one * 0.9f);

        InstantiatePrefabIfAvailable(tree, "Left Background Tree 01", parent, new Vector3(-10.2f, 0f, -8.2f), Quaternion.Euler(0f, 25f, 0f), Vector3.one);
        InstantiatePrefabIfAvailable(tree, "Left Background Tree 02", parent, new Vector3(-10.4f, 0f, 8.6f), Quaternion.Euler(0f, -18f, 0f), Vector3.one * 1.1f);
        InstantiatePrefabIfAvailable(tree, "Right Background Tree 01", parent, new Vector3(10.4f, 0f, -6.9f), Quaternion.Euler(0f, 66f, 0f), Vector3.one);
        InstantiatePrefabIfAvailable(rocks, "Street Rocks", parent, new Vector3(-4.8f, 0f, 3.8f), Quaternion.Euler(0f, 24f, 0f), Vector3.one);
    }

    static PatrolNpcController CreateNpc(
        string name,
        Transform root,
        HarPlayerStealth player,
        string characterPrefabPath,
        RuntimeAnimatorController npcAnimatorController,
        Material npcMaterial,
        Material coneMaterial,
        Material waypointMaterial,
        Vector3[] path,
        float patrolSpeed)
    {
        GameObject pathRoot = new GameObject($"{name} Waypoints");
        pathRoot.transform.SetParent(root);

        Transform[] waypoints = new Transform[path.Length];
        for (int i = 0; i < path.Length; i++)
        {
            GameObject waypoint = new GameObject($"{name} Waypoint {i + 1}");
            waypoint.transform.SetParent(pathRoot.transform);
            waypoint.transform.position = path[i];
            waypoints[i] = waypoint.transform;
        }

        GameObject npcObject = new GameObject(name);
        npcObject.transform.SetParent(root);
        npcObject.transform.position = path[0];

        Vector3 initialForward = path.Length > 1 ? path[1] - path[0] : Vector3.forward;
        initialForward.y = 0f;
        npcObject.transform.rotation = Quaternion.LookRotation(initialForward.normalized, Vector3.up);

        var renderers = new List<Renderer>();
        Transform head = null;
        Transform neck = null;
        Animator animator = null;

        GameObject character = InstantiatePrefabIfAvailable(characterPrefabPath, $"{name} Synty Character", npcObject.transform, npcObject.transform.position, npcObject.transform.rotation, Vector3.one);
        bool hasSyntyCharacter = character != null;

        if (hasSyntyCharacter)
        {
            character.transform.localPosition = Vector3.zero;
            character.transform.localRotation = Quaternion.identity;
            character.transform.localScale = Vector3.one;
            SnapRendererBottomTo(character, npcObject.transform.position.y);
            renderers.AddRange(character.GetComponentsInChildren<Renderer>(true));
            head = FindChildByNamePart(character.transform, "Head");
            neck = FindChildByNamePart(character.transform, "Neck");
            animator = character.GetComponentInChildren<Animator>();

            if (animator != null && npcAnimatorController != null)
            {
                animator.runtimeAnimatorController = npcAnimatorController;
                animator.applyRootMotion = false;
            }
        }
        else
        {
            GameObject body = CreatePrimitive(PrimitiveType.Capsule, "Body", npcObject.transform, npcObject.transform.position + new Vector3(0f, 0.82f, 0f), new Vector3(0.42f, 0.72f, 0.42f), npcMaterial);
            GameObject fallbackHead = CreatePrimitive(PrimitiveType.Sphere, "Head", npcObject.transform, npcObject.transform.position + new Vector3(0f, 1.62f, 0f), Vector3.one * 0.38f, npcMaterial);
            GameObject leftArm = CreatePrimitive(PrimitiveType.Cube, "Left Arm", npcObject.transform, npcObject.transform.position + new Vector3(-0.42f, 0.95f, 0.05f), new Vector3(0.16f, 0.58f, 0.16f), npcMaterial);
            GameObject rightArm = CreatePrimitive(PrimitiveType.Cube, "Right Arm", npcObject.transform, npcObject.transform.position + new Vector3(0.42f, 0.95f, 0.05f), new Vector3(0.16f, 0.58f, 0.16f), npcMaterial);

            foreach (GameObject part in new[] { body, fallbackHead, leftArm, rightArm })
            {
                Object.DestroyImmediate(part.GetComponent<Collider>());
                renderers.Add(part.GetComponent<Renderer>());
            }

            head = fallbackHead.transform;
        }

        GameObject visionOrigin = new GameObject("Vision Origin");
        visionOrigin.transform.SetParent(npcObject.transform);
        visionOrigin.transform.localPosition = new Vector3(0f, 1.5f, 0.22f);

        PatrolNpcController controller = npcObject.AddComponent<PatrolNpcController>();
        controller.player = player;
        controller.waypoints = waypoints;
        controller.patrolSpeed = patrolSpeed;
        controller.visionOrigin = visionOrigin.transform;
        controller.visionAngle = 65f;
        controller.visionDistance = 6.5f;
        controller.tintBodyOnState = !hasSyntyCharacter;
        controller.bodyRenderers = renderers.Where(renderer => renderer != null).ToArray();

        if (animator != null)
        {
            NpcAnimatorDriver animationDriver = npcObject.AddComponent<NpcAnimatorDriver>();
            animationDriver.npc = controller;
            animationDriver.animator = animator;
        }

        NpcHeadLookAt headLook = npcObject.AddComponent<NpcHeadLookAt>();
        headLook.npc = controller;
        headLook.target = player.cameraTransform != null ? player.cameraTransform : player.transform;
        headLook.head = head;
        headLook.neck = neck;
        headLook.trackingDistance = 9f;
        headLook.maxYaw = 72f;
        headLook.maxPitch = 30f;
        headLook.turnSpeed = 9f;

        GameObject cone = new GameObject("Red Vision Cone");
        cone.transform.SetParent(npcObject.transform);
        cone.transform.localPosition = new Vector3(0f, 0.055f, 0.18f);
        cone.transform.localRotation = Quaternion.identity;
        cone.AddComponent<MeshFilter>();
        MeshRenderer coneRenderer = cone.AddComponent<MeshRenderer>();
        coneRenderer.sharedMaterial = coneMaterial;

        NpcVisionConeRenderer coneRendererScript = cone.AddComponent<NpcVisionConeRenderer>();
        coneRendererScript.npc = controller;
        coneRendererScript.distance = controller.visionDistance;
        coneRendererScript.angle = controller.visionAngle;

        return controller;
    }

    static void BuildStatusPanel(Transform root, HarBridgeLauncher bridge, HarActivityState state, HarPlayerStealth player, Material panelMaterial)
    {
        GameObject background = CreatePrimitive(PrimitiveType.Cube, "Status Panel Background", root, new Vector3(42.0f, 1.95f, -2.15f), new Vector3(3.5f, 1.7f, 0.04f), panelMaterial);
        Object.DestroyImmediate(background.GetComponent<Collider>());

        GameObject textObject = new GameObject("Status Panel Text");
        textObject.transform.SetParent(root);
        textObject.transform.position = new Vector3(40.35f, 2.55f, -2.22f);
        textObject.transform.rotation = Quaternion.identity;

        TextMeshPro text = textObject.AddComponent<TextMeshPro>();
        text.text = "HARVR STEALTH DEMO";
        text.color = Color.white;
        text.fontSize = 0.18f;
        text.alignment = TextAlignmentOptions.TopLeft;
        text.textWrappingMode = TextWrappingModes.NoWrap;
        text.rectTransform.sizeDelta = new Vector2(3.35f, 1.4f);

        HarDemoStatusPanel statusPanel = textObject.AddComponent<HarDemoStatusPanel>();
        statusPanel.statusText = text;
        statusPanel.bridgeLauncher = bridge;
        statusPanel.activityState = state;
        statusPanel.playerStealth = player;
    }

    static void BuildPairingPanel(Transform root, HarBridgeLauncher bridge)
    {
        GameObject canvasObject = new GameObject("HARVR Pairing Panel");
        canvasObject.transform.SetParent(root);
        canvasObject.transform.position = new Vector3(45f, 1.55f, -1.95f);
        canvasObject.transform.rotation = Quaternion.identity;
        canvasObject.transform.localScale = Vector3.one * 0.006f;

        Canvas canvas = canvasObject.AddComponent<Canvas>();
        canvas.renderMode = RenderMode.WorldSpace;
        canvas.sortingOrder = 12;

        RectTransform canvasRect = canvasObject.GetComponent<RectTransform>();
        canvasRect.sizeDelta = new Vector2(560f, 340f);

        CanvasScaler scaler = canvasObject.AddComponent<CanvasScaler>();
        scaler.dynamicPixelsPerUnit = 12f;

        canvasObject.AddComponent<GraphicRaycaster>();
        AddTrackedDeviceRaycasterIfAvailable(canvasObject);

        Image background = canvasObject.AddComponent<Image>();
        background.color = new Color(0.02f, 0.025f, 0.03f, 0.9f);

        TextMeshProUGUI title = CreateUiText("Title", canvasRect, "HARVR Pairing", new Vector2(0f, 118f), new Vector2(500f, 48f), 34f, FontStyles.Bold);
        title.alignment = TextAlignmentOptions.Center;

        TextMeshProUGUI helper = CreateUiText("Help Text", canvasRect, "Enter the remote pairing code, then start the server.", new Vector2(0f, 77f), new Vector2(500f, 34f), 18f, FontStyles.Normal);
        helper.alignment = TextAlignmentOptions.Center;
        helper.color = new Color(0.82f, 0.9f, 1f, 1f);

        TMP_InputField input = CreatePairingInput(canvasRect, new Vector2(0f, 24f), new Vector2(360f, 52f));
        Button button = CreateUiButton(canvasRect, "Start Server Button", "Start Server", new Vector2(0f, -43f), new Vector2(250f, 52f), out TextMeshProUGUI buttonLabel);

        TextMeshProUGUI status = CreateUiText("Pairing Status", canvasRect, "Waiting for pairing code", new Vector2(0f, -100f), new Vector2(500f, 34f), 20f, FontStyles.Bold);
        status.alignment = TextAlignmentOptions.Center;
        status.color = new Color(1f, 0.86f, 0.36f, 1f);

        HarPairingUIController pairing = canvasObject.AddComponent<HarPairingUIController>();
        pairing.bridgeLauncher = bridge;
        pairing.pairingInputField = input;
        pairing.connectButton = button;
        pairing.connectButtonLabel = buttonLabel;
        pairing.statusText = status;
    }

    static TMP_InputField CreatePairingInput(Transform parent, Vector2 anchoredPosition, Vector2 size)
    {
        GameObject inputObject = CreateUiRect("Pairing Code Input", parent, anchoredPosition, size);
        Image inputBackground = inputObject.AddComponent<Image>();
        inputBackground.color = new Color(0.93f, 0.96f, 1f, 0.96f);

        TMP_InputField input = inputObject.AddComponent<TMP_InputField>();
        input.characterLimit = 16;
        input.lineType = TMP_InputField.LineType.SingleLine;
        input.contentType = TMP_InputField.ContentType.Alphanumeric;
        input.text = "";

        GameObject viewportObject = CreateUiRect("Text Area", inputObject.transform, Vector2.zero, size - new Vector2(26f, 14f));
        viewportObject.AddComponent<RectMask2D>();
        RectTransform viewport = viewportObject.GetComponent<RectTransform>();

        TextMeshProUGUI placeholder = CreateUiText("Placeholder", viewport, "Pairing code", Vector2.zero, size - new Vector2(34f, 18f), 24f, FontStyles.Normal);
        placeholder.color = new Color(0.32f, 0.36f, 0.42f, 0.72f);
        placeholder.alignment = TextAlignmentOptions.MidlineLeft;

        TextMeshProUGUI text = CreateUiText("Text", viewport, "", Vector2.zero, size - new Vector2(34f, 18f), 24f, FontStyles.Bold);
        text.color = Color.black;
        text.alignment = TextAlignmentOptions.MidlineLeft;

        input.textViewport = viewport;
        input.textComponent = text;
        input.placeholder = placeholder;
        return input;
    }

    static Button CreateUiButton(Transform parent, string name, string label, Vector2 anchoredPosition, Vector2 size, out TextMeshProUGUI labelText)
    {
        GameObject buttonObject = CreateUiRect(name, parent, anchoredPosition, size);
        Image image = buttonObject.AddComponent<Image>();
        image.color = new Color(0.08f, 0.42f, 0.78f, 1f);

        Button button = buttonObject.AddComponent<Button>();
        ColorBlock colors = button.colors;
        colors.normalColor = new Color(0.08f, 0.42f, 0.78f, 1f);
        colors.highlightedColor = new Color(0.12f, 0.55f, 0.96f, 1f);
        colors.pressedColor = new Color(0.04f, 0.28f, 0.58f, 1f);
        colors.disabledColor = new Color(0.24f, 0.28f, 0.32f, 0.9f);
        button.colors = colors;

        labelText = CreateUiText("Label", buttonObject.transform, label, Vector2.zero, size, 22f, FontStyles.Bold);
        labelText.alignment = TextAlignmentOptions.Center;
        return button;
    }

    static TextMeshProUGUI CreateUiText(string name, Transform parent, string text, Vector2 anchoredPosition, Vector2 size, float fontSize, FontStyles style)
    {
        GameObject textObject = CreateUiRect(name, parent, anchoredPosition, size);
        TextMeshProUGUI label = textObject.AddComponent<TextMeshProUGUI>();
        label.text = text;
        label.fontSize = fontSize;
        label.fontStyle = style;
        label.color = Color.white;
        label.alignment = TextAlignmentOptions.MidlineLeft;
        label.raycastTarget = false;
        return label;
    }

    static GameObject CreateUiRect(string name, Transform parent, Vector2 anchoredPosition, Vector2 size)
    {
        GameObject gameObject = new GameObject(name);
        gameObject.transform.SetParent(parent, false);

        RectTransform rect = gameObject.AddComponent<RectTransform>();
        rect.anchorMin = new Vector2(0.5f, 0.5f);
        rect.anchorMax = new Vector2(0.5f, 0.5f);
        rect.pivot = new Vector2(0.5f, 0.5f);
        rect.anchoredPosition = anchoredPosition;
        rect.sizeDelta = size;
        return gameObject;
    }

    static void AddTrackedDeviceRaycasterIfAvailable(GameObject canvasObject)
    {
        Type raycasterType = Type.GetType("UnityEngine.XR.Interaction.Toolkit.UI.TrackedDeviceGraphicRaycaster, Unity.XR.Interaction.Toolkit");

        if (raycasterType != null && canvasObject.GetComponent(raycasterType) == null)
            canvasObject.AddComponent(raycasterType);
    }

    static void EnsureEventSystem()
    {
        if (Object.FindAnyObjectByType<EventSystem>() != null)
            return;

        GameObject eventSystemObject = new GameObject("EventSystem");
        eventSystemObject.AddComponent<EventSystem>();

#if ENABLE_INPUT_SYSTEM
        eventSystemObject.AddComponent<InputSystemUIInputModule>();
#else
        eventSystemObject.AddComponent<StandaloneInputModule>();
#endif
    }

    static GameObject CreateBushCluster(string name, Transform root, Vector3 position, Vector3 size, Material material)
    {
        GameObject bush = new GameObject(name);
        bush.transform.SetParent(root);
        bush.transform.position = position;

        BoxCollider collider = bush.AddComponent<BoxCollider>();
        collider.size = size;
        collider.isTrigger = true;
        bush.AddComponent<HarCoverZone>();

        string[] prefabPaths =
        {
            "Assets/PolygonTown/Prefabs/Environment/SM_Env_Hedge_01.prefab",
            "Assets/PolygonTown/Prefabs/Environment/SM_Env_Bush_02.prefab",
            "Assets/PolygonTown/Prefabs/Environment/SM_Env_Hedge_02.prefab",
            "Assets/PolygonTown/Prefabs/Environment/SM_Env_Bush_03.prefab",
            "Assets/PolygonTown/Prefabs/Environment/SM_Env_Hedge_03.prefab",
        };

        Vector3[] offsets =
        {
            new Vector3(-0.35f, -0.46f, -0.33f),
            new Vector3(0.28f, -0.46f, -0.15f),
            new Vector3(-0.06f, -0.46f, 0.32f),
            new Vector3(0.42f, -0.46f, 0.36f),
            new Vector3(-0.5f, -0.46f, 0.14f),
        };

        float[] yaws = { -18f, 33f, 102f, 161f, -126f };
        float[] scales = { 1.05f, 0.96f, 1.08f, 0.98f, 0.86f };

        for (int i = 0; i < offsets.Length; i++)
        {
            GameObject visual = InstantiatePrefabIfAvailable(prefabPaths[i % prefabPaths.Length], $"{name} Synty Cover {i + 1}", bush.transform, position, Quaternion.identity, Vector3.one);

            if (visual == null)
            {
                visual = CreatePrimitive(PrimitiveType.Capsule, $"{name} Fallback Shrub {i + 1}", bush.transform, position, Vector3.one, material);
                Object.DestroyImmediate(visual.GetComponent<Collider>());
            }

            visual.transform.localPosition = Vector3.Scale(offsets[i], size);
            visual.transform.localRotation = Quaternion.Euler(0f, yaws[i], 0f);
            float clusterScale = Mathf.Clamp(Mathf.Max(size.x, size.z) * 0.34f * scales[i], 0.75f, 1.35f);
            visual.transform.localScale = Vector3.one * clusterScale;
        }

        return bush;
    }

    static GameObject CreateCoverTrigger(string name, Transform root, Vector3 position, Vector3 size)
    {
        GameObject cover = new GameObject(name);
        cover.transform.SetParent(root);
        cover.transform.position = position;

        BoxCollider collider = cover.AddComponent<BoxCollider>();
        collider.size = size;
        collider.isTrigger = true;

        cover.AddComponent<HarCoverZone>();
        AddTallGrassCoverVisuals(cover.transform, size);
        return cover;
    }

    static void AddTallGrassCoverVisuals(Transform cover, Vector3 triggerSize)
    {
        Vector3[] offsets =
        {
            new Vector3(-0.32f, -0.46f, -0.22f),
            new Vector3(0.26f, -0.46f, -0.12f),
            new Vector3(-0.08f, -0.46f, 0.22f),
            new Vector3(0.34f, -0.46f, 0.22f),
            new Vector3(-0.36f, -0.46f, 0.18f),
        };

        float[] yaws = { -18f, 41f, 96f, 151f, -124f };
        Vector3[] scales =
        {
            new Vector3(1.45f, 3.15f, 1.2f),
            new Vector3(1.22f, 2.8f, 1.1f),
            new Vector3(1.55f, 3.35f, 1.25f),
            new Vector3(1.18f, 2.65f, 1.05f),
            new Vector3(1.35f, 3.0f, 1.2f),
        };

        for (int i = 0; i < offsets.Length; i++)
        {
            GameObject grass = InstantiatePrefabIfAvailable(
                TallGrassCoverPrefabPath,
                $"{cover.name} Tall Grass {i + 1}",
                cover,
                cover.position,
                Quaternion.identity,
                Vector3.one);

            if (grass == null)
                continue;

            grass.transform.localPosition = Vector3.Scale(offsets[i], triggerSize);
            grass.transform.localRotation = Quaternion.Euler(0f, yaws[i], 0f);
            grass.transform.localScale = scales[i];
            MakeVisualOnly(grass);
        }
    }

    static void MakeVisualOnly(GameObject gameObject)
    {
        foreach (Collider collider in gameObject.GetComponentsInChildren<Collider>(true))
            Object.DestroyImmediate(collider);
    }

    static RuntimeAnimatorController GetOrCreateNpcAnimatorController()
    {
        AssetDatabase.ImportAsset(NpcIdleClipPath, ImportAssetOptions.ForceUpdate);
        AssetDatabase.ImportAsset(NpcWalkClipPath, ImportAssetOptions.ForceUpdate);

        AnimationClip idleClip = FindClipAtPath(NpcIdleClipPath, "Idle");
        AnimationClip walkClip = FindClipAtPath(NpcWalkClipPath, "Walk");

        if (idleClip == null || walkClip == null)
        {
            Debug.LogWarning("[HARVR] NPC animation clips were not found. NPCs will keep their static pose.");
            return null;
        }

        AssetDatabase.DeleteAsset(NpcAnimatorControllerPath);
        AnimatorController controller = AnimatorController.CreateAnimatorControllerAtPath(NpcAnimatorControllerPath);
        controller.AddParameter("Speed", AnimatorControllerParameterType.Float);

        AnimatorStateMachine stateMachine = controller.layers[0].stateMachine;
        AnimatorState idleState = stateMachine.AddState("Idle");
        idleState.motion = idleClip;
        idleState.speed = 1f;
        stateMachine.defaultState = idleState;

        AnimatorState walkState = stateMachine.AddState("Walk");
        walkState.motion = walkClip;
        walkState.speed = 1f;

        AnimatorStateTransition toWalk = idleState.AddTransition(walkState);
        toWalk.hasExitTime = false;
        toWalk.duration = 0.12f;
        toWalk.AddCondition(AnimatorConditionMode.Greater, 0.08f, "Speed");

        AnimatorStateTransition toIdle = walkState.AddTransition(idleState);
        toIdle.hasExitTime = false;
        toIdle.duration = 0.12f;
        toIdle.AddCondition(AnimatorConditionMode.Less, 0.04f, "Speed");

        AssetDatabase.SaveAssets();
        return controller;
    }

    static AnimationClip FindClipAtPath(string path, string namePart)
    {
        foreach (Object asset in AssetDatabase.LoadAllAssetsAtPath(path))
        {
            if (asset is AnimationClip clip && !clip.name.StartsWith("__preview__", StringComparison.OrdinalIgnoreCase))
            {
                if (clip.name.IndexOf(namePart, StringComparison.OrdinalIgnoreCase) >= 0)
                    return clip;
            }
        }

        return AssetDatabase.LoadAllAssetsAtPath(path).OfType<AnimationClip>().FirstOrDefault(clip => !clip.name.StartsWith("__preview__", StringComparison.OrdinalIgnoreCase));
    }

    static void PlacePrefab(string name, string prefabPath, Transform parent, Vector3 position, float yaw)
    {
        InstantiatePrefabIfAvailable(prefabPath, name, parent, position, Quaternion.Euler(0f, yaw, 0f), Vector3.one);
    }

    static GameObject InstantiatePrefabIfAvailable(string prefabPath, string name, Transform parent, Vector3 position, Quaternion rotation, Vector3 scale)
    {
        GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
        if (prefab == null)
            return null;

        GameObject instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab, parent);
        if (instance == null)
            instance = Object.Instantiate(prefab, parent);

        instance.name = name;
        instance.transform.position = position;
        instance.transform.rotation = rotation;
        instance.transform.localScale = scale;
        return instance;
    }

    static GameObject CreatePrefabOrPrimitive(
        string prefabPath,
        string name,
        Transform parent,
        Vector3 position,
        Quaternion rotation,
        Vector3 prefabScale,
        PrimitiveType fallbackType,
        Vector3 fallbackScale,
        Material fallbackMaterial)
    {
        GameObject instance = InstantiatePrefabIfAvailable(prefabPath, name, parent, position, rotation, prefabScale);
        if (instance != null)
            return instance;

        GameObject fallback = CreatePrimitive(fallbackType, name, parent, position, fallbackScale, fallbackMaterial);
        fallback.transform.rotation = rotation;
        return fallback;
    }

    static void SnapRendererBottomTo(GameObject gameObject, float groundY)
    {
        Renderer[] renderers = gameObject.GetComponentsInChildren<Renderer>(true);
        if (renderers.Length == 0)
            return;

        Bounds bounds = renderers[0].bounds;
        for (int i = 1; i < renderers.Length; i++)
            bounds.Encapsulate(renderers[i].bounds);

        gameObject.transform.position += Vector3.up * (groundY - bounds.min.y);
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

    static GameObject CreatePrimitive(PrimitiveType type, string name, Transform parent, Vector3 position, Vector3 scale, Material material)
    {
        GameObject gameObject = GameObject.CreatePrimitive(type);
        gameObject.name = name;
        gameObject.transform.SetParent(parent);
        gameObject.transform.position = position;
        gameObject.transform.localScale = scale;

        Renderer renderer = gameObject.GetComponent<Renderer>();
        if (renderer != null && material != null)
            renderer.sharedMaterial = material;

        return gameObject;
    }

    static Material GetOrCreateMaterial(string path, Color color, bool transparent)
    {
        Material material = AssetDatabase.LoadAssetAtPath<Material>(path);

        if (material == null)
        {
            Shader shader = Shader.Find("Universal Render Pipeline/Lit");
            if (shader == null)
                shader = Shader.Find("Standard");

            material = new Material(shader);
            AssetDatabase.CreateAsset(material, path);
        }

        if (material.HasProperty("_BaseColor"))
            material.SetColor("_BaseColor", color);
        if (material.HasProperty("_Color"))
            material.SetColor("_Color", color);

        if (transparent)
        {
            material.SetFloat("_Surface", 1f);
            material.SetFloat("_Blend", 0f);
            material.SetFloat("_SrcBlend", (float)BlendMode.SrcAlpha);
            material.SetFloat("_DstBlend", (float)BlendMode.OneMinusSrcAlpha);
            material.SetFloat("_ZWrite", 0f);
            material.SetFloat("_Cull", (float)CullMode.Off);
            material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.renderQueue = (int)RenderQueue.Transparent;
        }
        else
        {
            material.SetFloat("_Surface", 0f);
            material.SetFloat("_ZWrite", 1f);
            material.SetFloat("_Cull", (float)CullMode.Back);
            material.renderQueue = -1;
        }

        EditorUtility.SetDirty(material);
        return material;
    }

    static GameObject FindXrOriginOrCreateFallback()
    {
        GameObject xrOrigin = FindSceneObjectByNameContains("XR Origin") ?? FindSceneObjectByNameContains("XROrigin");

        if (xrOrigin != null)
            return xrOrigin;

        xrOrigin = CloneXrOriginFromBasicScene();
        if (xrOrigin != null)
            return xrOrigin;

        GameObject fallback = new GameObject("XR Origin (Fallback Demo Rig)");
        Camera camera = new GameObject("Main Camera").AddComponent<Camera>();
        camera.tag = "MainCamera";
        camera.transform.SetParent(fallback.transform);
        camera.transform.localPosition = new Vector3(0f, 1.65f, 0f);
        return fallback;
    }

    static GameObject CloneXrOriginFromBasicScene()
    {
        if (!File.Exists(BasicScenePath))
            return null;

        Scene targetScene = SceneManager.GetActiveScene();
        Scene sourceScene = EditorSceneManager.OpenScene(BasicScenePath, OpenSceneMode.Additive);

        GameObject sourceOrigin = FindXrOriginInScene(sourceScene);
        GameObject clone = null;

        if (sourceOrigin != null)
        {
            clone = Object.Instantiate(sourceOrigin);
            clone.name = sourceOrigin.name;
            SceneManager.MoveGameObjectToScene(clone, targetScene);
        }

        EditorSceneManager.CloseScene(sourceScene, true);
        EditorSceneManager.SetActiveScene(targetScene);
        return clone;
    }

    static GameObject FindXrOriginInScene(Scene scene)
    {
        foreach (GameObject root in scene.GetRootGameObjects())
        {
            if (root.name.Contains("XR Origin") || root.name.Contains("XROrigin"))
                return root;

            foreach (Transform child in root.GetComponentsInChildren<Transform>(true))
            {
                if (child.name.Contains("XR Origin") || child.name.Contains("XROrigin"))
                    return child.gameObject;
            }
        }

        return null;
    }

    static Transform FindMainCameraTransform(Transform preferredRoot)
    {
        Camera[] cameras = Object.FindObjectsByType<Camera>();

        foreach (Camera camera in cameras)
        {
            if (camera != null && camera.CompareTag("MainCamera") && camera.transform.IsChildOf(preferredRoot))
                return camera.transform;
        }

        Camera mainCamera = Camera.main;
        if (mainCamera != null)
            return mainCamera.transform;

        return preferredRoot;
    }

    static void DisableExtraSceneCameras(Transform keepCamera)
    {
        Camera[] cameras = Object.FindObjectsByType<Camera>();

        foreach (Camera camera in cameras)
        {
            if (camera == null)
                continue;

            if (keepCamera != null && camera.transform == keepCamera)
            {
                camera.enabled = true;
                camera.tag = "MainCamera";
                continue;
            }

            camera.enabled = false;

            if (camera.CompareTag("MainCamera"))
                camera.tag = "Untagged";
        }
    }

    static GameObject FindSceneObjectByNameContains(string namePart)
    {
        GameObject[] gameObjects = Object.FindObjectsByType<GameObject>();

        foreach (GameObject gameObject in gameObjects)
        {
            if (gameObject.scene.IsValid() && gameObject.name.Contains(namePart))
                return gameObject;
        }

        return null;
    }

    static T GetOrAdd<T>(GameObject gameObject) where T : Component
    {
        T component = gameObject.GetComponent<T>();
        return component != null ? component : gameObject.AddComponent<T>();
    }

    static void ConfigureLighting()
    {
        Light directional = Object.FindAnyObjectByType<Light>();

        if (directional != null)
        {
            directional.transform.rotation = Quaternion.Euler(45f, -25f, 0f);
            directional.intensity = 1.2f;
        }

        RenderSettings.ambientIntensity = 1.05f;
    }

    static void AddSceneToBuildSettings(string scenePath)
    {
        List<EditorBuildSettingsScene> scenes = EditorBuildSettings.scenes.ToList();

        if (scenes.All(scene => scene.path != scenePath))
            scenes.Add(new EditorBuildSettingsScene(scenePath, true));

        EditorBuildSettings.scenes = scenes.ToArray();
    }

    static void EnsureAssetFolder(string path)
    {
        if (AssetDatabase.IsValidFolder(path))
            return;

        string parent = Path.GetDirectoryName(path)?.Replace("\\", "/");
        string name = Path.GetFileName(path);

        if (!string.IsNullOrEmpty(parent))
            EnsureAssetFolder(parent);

        AssetDatabase.CreateFolder(parent, name);
    }

    static void MoveToScene(GameObject gameObject, Scene scene)
    {
        if (gameObject.scene != scene)
            SceneManager.MoveGameObjectToScene(gameObject, scene);
    }
}
