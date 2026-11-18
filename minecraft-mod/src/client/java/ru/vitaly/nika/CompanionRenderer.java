package ru.vitaly.nika;

import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.rendering.v1.world.WorldRenderContext;
import net.fabricmc.fabric.api.client.rendering.v1.world.WorldRenderEvents;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.renderer.entity.state.EntityRenderState;
import net.minecraft.client.renderer.state.CameraRenderState;
import net.minecraft.util.Mth;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.animal.allay.Allay;
import net.minecraft.world.phys.Vec3;

import java.util.Random;

/**
 * Renders a private, client-only visual companion.
 *
 * The Allay instance is never added to ClientLevel. It cannot be tracked by a
 * server, collide with gameplay entities, pick up items or interact with the
 * world. Only its vanilla render state is submitted to the client renderer.
 */
final class CompanionRenderer {
    private static final double SIDE_OFFSET = 0.90;
    private static final double TRAIL_DISTANCE = 1.15;
    private static final double HEIGHT_OFFSET = 0.95;
    private static final double INITIAL_FORWARD_OFFSET = 0.55;

    private static final double MOVEMENT_THRESHOLD_SQUARED = 0.0004;
    private static final double TELEPORT_DISTANCE = 12.0;

    // Critically damped follow in real-time units (blocks/second).
    // Nika changes pace in slow, smooth phases instead of keeping a fixed speed.
    private static final double FOLLOW_SMOOTH_TIME = 0.38;
    private static final double FOLLOW_SPEED_MIN = 3.6;
    private static final double FOLLOW_SPEED_MAX = 7.0;
    private static final double FOLLOW_SPEED_BASE = 5.2;
    private static final double FOLLOW_PACE_RESPONSE_MOVING = 0.035;
    private static final double FOLLOW_PACE_RESPONSE_IDLE = 0.06;
    private static final int FOLLOW_PACE_MIN_DELAY = 45;
    private static final int FOLLOW_PACE_MAX_DELAY = 100;
    private static final double TICK_SECONDS = 1.0 / 20.0;
    private static final double ARRIVAL_DISTANCE = 0.025;

    private static final double IDLE_WANDER_MIN_RADIUS = 0.10;
    private static final double IDLE_WANDER_MAX_RADIUS = 0.30;
    private static final int IDLE_WANDER_MIN_DELAY = 90;
    private static final int IDLE_WANDER_MAX_DELAY = 170;
    private static final int IDLE_LOOK_MIN_DELAY = 55;
    private static final int IDLE_LOOK_MAX_DELAY = 125;

    // Rotation response is deliberately slower than position response.
    private static final float BODY_TURN_WHILE_MOVING = 0.12F;
    private static final float BODY_TURN_WHILE_IDLE = 0.045F;
    private static final float HEAD_TURN_RESPONSE = 0.13F;
    private static final float MAX_HEAD_RELATIVE_YAW = 78.0F;

    private static final double BOB_AMPLITUDE = 0.065;
    private static final double BOB_SPEED = 0.105;

    private static final Random RANDOM = new Random();

    private static boolean enabled;
    private static boolean wasMoving;

    private static Allay avatar;
    private static ClientLevel avatarLevel;

    private static Vec3 desiredPosition;
    private static Vec3 smoothedPosition;
    private static Vec3 followVelocity = Vec3.ZERO;
    private static double followSpeed = FOLLOW_SPEED_BASE;
    private static double targetFollowSpeed = FOLLOW_SPEED_BASE;
    private static long nextFollowPaceTick;
    private static Vec3 previousPlayerPosition;
    private static Vec3 travelDirection = new Vec3(0.0, 0.0, 1.0);

    private static Vec3 idleAnchor;
    private static Vec3 idleWanderOffset = Vec3.ZERO;
    private static Vec3 lookTarget;

    private static long nextIdleWanderTick;
    private static long nextIdleLookTick;

    private static float bodyYaw;
    private static float headYaw;

    private CompanionRenderer() {
    }

    static void initialize() {
        ClientTickEvents.END_CLIENT_TICK.register(CompanionRenderer::tick);
        WorldRenderEvents.BEFORE_ENTITIES.register(CompanionRenderer::render);
    }

    static boolean isEnabled() {
        return enabled;
    }

    static void summon() {
        enabled = true;
    }

    static void dismiss() {
        enabled = false;
        clearAvatar();
    }

    private static void tick(Minecraft client) {
        if (!enabled || client.player == null || client.level == null) {
            clearAvatar();
            return;
        }

        var player = client.player;
        ClientLevel level = client.level;
        Vec3 playerPosition = player.position();
        long gameTime = level.getGameTime();

        if (avatar == null || avatarLevel != level) {
            createAvatar(level, playerPosition, player.getYRot(), player.getEyePosition(), gameTime);
        }

        Vec3 horizontalMovement = playerPosition.subtract(previousPlayerPosition);
        horizontalMovement = new Vec3(horizontalMovement.x, 0.0, horizontalMovement.z);
        boolean moving = horizontalMovement.lengthSqr() > MOVEMENT_THRESHOLD_SQUARED;

        if (moving) {
            updateTravelDirection(horizontalMovement);
            updateMovingTarget(playerPosition);
            lookTarget = player.getEyePosition();
        } else {
            if (wasMoving || idleAnchor == null) {
                enterIdle(playerPosition, gameTime, player.getEyePosition());
            }
            updateIdleBehaviour(playerPosition, gameTime, player.getEyePosition());
        }

        previousPlayerPosition = playerPosition;
        wasMoving = moving;

        updateFollowPace(gameTime, moving);
        updateFollowMotion();

        // Keep previous body/head angles for vanilla render-state interpolation.
        avatar.setOldPosAndRot();
        avatar.yBodyRotO = avatar.yBodyRot;
        avatar.yHeadRotO = avatar.yHeadRot;

        updateOrientation(playerPosition, moving);

        double bob = Math.sin(gameTime * BOB_SPEED) * BOB_AMPLITUDE;
        avatar.setPos(
            smoothedPosition.x,
            smoothedPosition.y + bob,
            smoothedPosition.z
        );
        avatar.tickCount++;
    }

    /**
     * Low-pass the actual travel direction. This prevents tiny changes in
     * per-tick player movement from rotating Nika's target around the player.
     */
    private static void updateTravelDirection(Vec3 horizontalMovement) {
        Vec3 sampleDirection = horizontalMovement.normalize();
        double blend = travelDirection.dot(sampleDirection) < -0.25 ? 0.28 : 0.14;
        Vec3 blended = travelDirection.lerp(sampleDirection, blend);
        if (blended.lengthSqr() > 1.0E-6) {
            travelDirection = blended.normalize();
        } else {
            travelDirection = sampleDirection;
        }
    }

    private static void updateMovingTarget(Vec3 playerPosition) {
        Vec3 right = new Vec3(travelDirection.z, 0.0, -travelDirection.x);
        desiredPosition = playerPosition
            .subtract(travelDirection.scale(TRAIL_DISTANCE))
            .add(right.scale(SIDE_OFFSET))
            .add(0.0, HEIGHT_OFFSET, 0.0);
        idleAnchor = null;
        idleWanderOffset = Vec3.ZERO;
    }

    private static void enterIdle(Vec3 playerPosition, long gameTime, Vec3 playerEyePosition) {
        // Freeze the current world-space spot. Camera turns do not affect it.
        Vec3 anchorSource = smoothedPosition != null ? smoothedPosition : desiredPosition;
        idleAnchor = new Vec3(
            anchorSource.x,
            playerPosition.y + HEIGHT_OFFSET,
            anchorSource.z
        );
        idleWanderOffset = Vec3.ZERO;
        desiredPosition = idleAnchor;
        lookTarget = playerEyePosition;
        nextIdleWanderTick = gameTime + randomDelay(IDLE_WANDER_MIN_DELAY, IDLE_WANDER_MAX_DELAY);
        nextIdleLookTick = gameTime + randomDelay(IDLE_LOOK_MIN_DELAY, IDLE_LOOK_MAX_DELAY);
    }

    /**
     * Small, infrequent movements around the idle anchor and deliberate gaze
     * changes give Nika life without making her orbit or leave conversation range.
     */
    private static void updateIdleBehaviour(
        Vec3 playerPosition,
        long gameTime,
        Vec3 playerEyePosition
    ) {
        if (gameTime >= nextIdleWanderTick) {
            double angle = RANDOM.nextDouble() * Math.PI * 2.0;
            double radius = IDLE_WANDER_MIN_RADIUS
                + RANDOM.nextDouble() * (IDLE_WANDER_MAX_RADIUS - IDLE_WANDER_MIN_RADIUS);
            idleWanderOffset = new Vec3(
                Math.cos(angle) * radius,
                0.0,
                Math.sin(angle) * radius
            );
            nextIdleWanderTick = gameTime
                + randomDelay(IDLE_WANDER_MIN_DELAY, IDLE_WANDER_MAX_DELAY);
        }

        if (gameTime >= nextIdleLookTick) {
            if (RANDOM.nextFloat() < 0.72F) {
                lookTarget = playerEyePosition;
            } else {
                double angle = RANDOM.nextDouble() * Math.PI * 2.0;
                double distance = 1.2 + RANDOM.nextDouble() * 1.4;
                lookTarget = new Vec3(
                    smoothedPosition.x + Math.cos(angle) * distance,
                    smoothedPosition.y + 0.15 + RANDOM.nextDouble() * 0.55,
                    smoothedPosition.z + Math.sin(angle) * distance
                );
            }
            nextIdleLookTick = gameTime
                + randomDelay(IDLE_LOOK_MIN_DELAY, IDLE_LOOK_MAX_DELAY);
        }

        desiredPosition = new Vec3(
            idleAnchor.x + idleWanderOffset.x,
            playerPosition.y + HEIGHT_OFFSET + idleWanderOffset.y,
            idleAnchor.z + idleWanderOffset.z
        );
    }

    /**
     * Pick a new cruising pace only every few seconds, then ease toward it.
     * Randomness is intentionally low-frequency: per-tick random speed changes
     * would create visible jitter rather than natural variation.
     */
    private static void updateFollowPace(long gameTime, boolean moving) {
        if (moving && gameTime >= nextFollowPaceTick) {
            targetFollowSpeed = FOLLOW_SPEED_MIN
                + RANDOM.nextDouble() * (FOLLOW_SPEED_MAX - FOLLOW_SPEED_MIN);
            nextFollowPaceTick = gameTime
                + randomDelay(FOLLOW_PACE_MIN_DELAY, FOLLOW_PACE_MAX_DELAY);
        } else if (!moving) {
            targetFollowSpeed = FOLLOW_SPEED_BASE;
            nextFollowPaceTick = gameTime
                + randomDelay(FOLLOW_PACE_MIN_DELAY, FOLLOW_PACE_MAX_DELAY);
        }

        double response = moving
            ? FOLLOW_PACE_RESPONSE_MOVING
            : FOLLOW_PACE_RESPONSE_IDLE;
        followSpeed += (targetFollowSpeed - followSpeed) * response;

        if (Math.abs(targetFollowSpeed - followSpeed) < 0.01) {
            followSpeed = targetFollowSpeed;
        }
    }

    /**
     * Critically damped spring integration (the same family of controller used
     * by SmoothDamp): velocity is stored in blocks/second and the timestep is
     * expressed in seconds. Unlike the previous steering controller, it does
     * not repeatedly rotate a capped velocity vector toward a moving target.
     *
     * This gives Nika a continuous trajectory when the player accelerates,
     * stops or changes direction, while the damping prevents overshoot.
     */
    private static void updateFollowMotion() {
        if (smoothedPosition == null) {
            smoothedPosition = desiredPosition;
            followVelocity = Vec3.ZERO;
            return;
        }

        Vec3 displacement = desiredPosition.subtract(smoothedPosition);
        double distance = displacement.length();
        if (distance > TELEPORT_DISTANCE) {
            smoothedPosition = desiredPosition;
            followVelocity = Vec3.ZERO;
            return;
        }

        double smoothTime = FOLLOW_SMOOTH_TIME;
        double omega = 2.0 / smoothTime;
        double x = omega * TICK_SECONDS;
        double exponential = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x);

        // Clamp the spring's working target to a finite catch-up speed without
        // changing the actual target or injecting a per-tick velocity impulse.
        double maxChange = followSpeed * smoothTime;
        Vec3 change = smoothedPosition.subtract(desiredPosition);
        double changeLength = change.length();
        if (changeLength > maxChange) {
            change = change.scale(maxChange / changeLength);
        }
        Vec3 clampedTarget = smoothedPosition.subtract(change);

        Vec3 temp = followVelocity.add(change.scale(omega)).scale(TICK_SECONDS);
        followVelocity = followVelocity.subtract(temp.scale(omega)).scale(exponential);
        smoothedPosition = clampedTarget.add(change.add(temp).scale(exponential));

        if (distance < ARRIVAL_DISTANCE && followVelocity.lengthSqr() < 0.0001) {
            smoothedPosition = desiredPosition;
            followVelocity = Vec3.ZERO;
        }
    }

    /**
     * The Allay uses separate body and head yaw values. Keeping them separate
     * is essential: the body turns slowly while the head can glance naturally.
     */
    private static void updateOrientation(Vec3 playerPosition, boolean moving) {
        Vec3 bodyLookTarget = moving
            ? smoothedPosition.add(travelDirection)
            : playerPosition.add(0.0, HEIGHT_OFFSET + 0.45, 0.0);

        float targetBodyYaw = yawTo(smoothedPosition, bodyLookTarget);
        float bodyResponse = moving
            ? BODY_TURN_WHILE_MOVING
            : BODY_TURN_WHILE_IDLE;
        bodyYaw = Mth.rotLerp(bodyResponse, bodyYaw, targetBodyYaw);

        Vec3 currentLookTarget = lookTarget != null
            ? lookTarget
            : playerPosition.add(0.0, HEIGHT_OFFSET + 0.45, 0.0);
        float targetHeadYaw = yawTo(smoothedPosition, currentLookTarget);

        // Vanilla mobs limit how far the head can turn away from the body.
        float relativeHeadYaw = Mth.wrapDegrees(targetHeadYaw - bodyYaw);
        relativeHeadYaw = Mth.clamp(
            relativeHeadYaw,
            -MAX_HEAD_RELATIVE_YAW,
            MAX_HEAD_RELATIVE_YAW
        );
        targetHeadYaw = bodyYaw + relativeHeadYaw;
        headYaw = Mth.rotLerp(HEAD_TURN_RESPONSE, headYaw, targetHeadYaw);

        avatar.setYRot(bodyYaw);
        avatar.setYBodyRot(bodyYaw);
        avatar.setYHeadRot(headYaw);
    }

    private static void createAvatar(
        ClientLevel level,
        Vec3 playerPosition,
        float playerYaw,
        Vec3 playerEyePosition,
        long gameTime
    ) {
        clearAvatar();

        avatar = new Allay(EntityType.ALLAY, level);
        avatar.setNoAi(true);
        avatar.setNoGravity(true);
        avatar.setSilent(true);
        avatarLevel = level;

        double yawRadians = Math.toRadians(playerYaw);
        Vec3 forward = new Vec3(-Math.sin(yawRadians), 0.0, Math.cos(yawRadians));
        Vec3 right = new Vec3(Math.cos(yawRadians), 0.0, Math.sin(yawRadians));

        desiredPosition = playerPosition
            .add(right.scale(SIDE_OFFSET))
            .add(forward.scale(INITIAL_FORWARD_OFFSET))
            .add(0.0, HEIGHT_OFFSET, 0.0);
        smoothedPosition = desiredPosition;
        followVelocity = Vec3.ZERO;
        followSpeed = FOLLOW_SPEED_BASE;
        targetFollowSpeed = FOLLOW_SPEED_BASE;
        nextFollowPaceTick = gameTime + randomDelay(FOLLOW_PACE_MIN_DELAY, FOLLOW_PACE_MAX_DELAY);
        previousPlayerPosition = playerPosition;
        travelDirection = forward;
        wasMoving = false;

        idleAnchor = new Vec3(
            desiredPosition.x,
            playerPosition.y + HEIGHT_OFFSET,
            desiredPosition.z
        );
        idleWanderOffset = Vec3.ZERO;
        lookTarget = playerEyePosition;
        nextIdleWanderTick = gameTime
            + randomDelay(IDLE_WANDER_MIN_DELAY, IDLE_WANDER_MAX_DELAY);
        nextIdleLookTick = gameTime
            + randomDelay(IDLE_LOOK_MIN_DELAY, IDLE_LOOK_MAX_DELAY);

        bodyYaw = yawTo(smoothedPosition, playerEyePosition);
        headYaw = bodyYaw;
        avatar.setPos(smoothedPosition.x, smoothedPosition.y, smoothedPosition.z);
        avatar.setYRot(bodyYaw);
        avatar.setYBodyRot(bodyYaw);
        avatar.setYHeadRot(headYaw);
        avatar.yBodyRotO = bodyYaw;
        avatar.yHeadRotO = headYaw;
    }

    private static int randomDelay(int minimum, int maximum) {
        return minimum + RANDOM.nextInt(maximum - minimum + 1);
    }

    private static float yawTo(Vec3 from, Vec3 to) {
        double dx = to.x - from.x;
        double dz = to.z - from.z;
        return (float) Math.toDegrees(Math.atan2(-dx, dz));
    }

    private static void clearAvatar() {
        avatar = null;
        avatarLevel = null;
        desiredPosition = null;
        smoothedPosition = null;
        followVelocity = Vec3.ZERO;
        followSpeed = FOLLOW_SPEED_BASE;
        targetFollowSpeed = FOLLOW_SPEED_BASE;
        nextFollowPaceTick = 0L;
        previousPlayerPosition = null;
        travelDirection = new Vec3(0.0, 0.0, 1.0);
        idleAnchor = null;
        idleWanderOffset = Vec3.ZERO;
        lookTarget = null;
        nextIdleWanderTick = 0L;
        nextIdleLookTick = 0L;
        wasMoving = false;
        bodyYaw = 0.0F;
        headYaw = 0.0F;
    }

    private static void render(WorldRenderContext context) {
        Minecraft client = Minecraft.getInstance();
        if (!enabled || avatar == null || client.player == null || client.level == null
            || avatarLevel != client.level) {
            return;
        }

        CameraRenderState camera = context.worldState().cameraRenderState;
        if (camera == null || !camera.initialized || camera.pos == null) {
            return;
        }

        float tickDelta = client.getDeltaTracker().getGameTimeDeltaPartialTick(true);
        EntityRenderState renderState = client.getEntityRenderDispatcher()
            .extractEntity(avatar, tickDelta);
        if (renderState == null) {
            return;
        }

        Vec3 cameraPosition = camera.pos;
        client.getEntityRenderDispatcher().submit(
            renderState,
            camera,
            avatar.getX() - cameraPosition.x,
            avatar.getY() - cameraPosition.y,
            avatar.getZ() - cameraPosition.z,
            context.matrices(),
            context.commandQueue()
        );
    }
}
