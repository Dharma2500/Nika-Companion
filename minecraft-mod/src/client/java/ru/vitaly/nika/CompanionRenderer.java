package ru.vitaly.nika;

import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.rendering.v1.world.WorldRenderContext;
import net.fabricmc.fabric.api.client.rendering.v1.world.WorldRenderEvents;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.renderer.entity.state.EntityRenderState;
import net.minecraft.client.renderer.state.CameraRenderState;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.animal.allay.Allay;
import net.minecraft.world.phys.Vec3;

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

    // Ignore tiny position noise so turning the camera never moves the anchor.
    private static final double MOVEMENT_THRESHOLD_SQUARED = 0.0004;

    // A damped spring gives the companion momentum instead of per-tick snapping.
    private static final double FOLLOW_SPRING = 0.18;
    private static final double FOLLOW_DAMPING = 0.62;
    private static final double MAX_FOLLOW_SPEED = 0.42;
    private static final double ARRIVAL_DISTANCE = 0.025;
    private static final double TELEPORT_DISTANCE = 12.0;

    private static final double BOB_AMPLITUDE = 0.065;
    private static final double BOB_SPEED = 0.105;

    private static boolean enabled;
    private static Allay avatar;
    private static ClientLevel avatarLevel;
    private static Vec3 desiredPosition;
    private static Vec3 smoothedPosition;
    private static Vec3 followVelocity = Vec3.ZERO;
    private static Vec3 previousPlayerPosition;

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

        if (avatar == null || avatarLevel != client.level) {
            createAvatar(client.level, client.player.position(), client.player.getYRot());
        }

        var player = client.player;
        Vec3 playerPosition = player.position();

        updateFollowTarget(playerPosition);
        updateFollowMotion();

        // Preserve the previous transform so the vanilla renderer can interpolate.
        avatar.setOldPosAndRot();
        double bob = Math.sin(client.level.getGameTime() * BOB_SPEED) * BOB_AMPLITUDE;
        avatar.setPos(
            smoothedPosition.x,
            smoothedPosition.y + bob,
            smoothedPosition.z
        );
        avatar.tickCount++;

        // Nika looks toward the player, not toward the camera direction.
        double dx = player.getX() - smoothedPosition.x;
        double dz = player.getZ() - smoothedPosition.z;
        float facingYaw = (float) (Math.atan2(dz, dx) * (180.0 / Math.PI)) - 90.0F;
        avatar.setYRot(facingYaw);
    }

    /**
     * While the player is moving, place Nika to the right and behind the
     * actual travel direction. When horizontal movement stops, keep the
     * world-space anchor fixed so turning to look at her cannot move her away.
     */
    private static void updateFollowTarget(Vec3 playerPosition) {
        if (previousPlayerPosition == null || desiredPosition == null) {
            previousPlayerPosition = playerPosition;
            return;
        }

        Vec3 movement = playerPosition.subtract(previousPlayerPosition);
        Vec3 horizontalMovement = new Vec3(movement.x, 0.0, movement.z);
        previousPlayerPosition = playerPosition;

        if (horizontalMovement.lengthSqr() > MOVEMENT_THRESHOLD_SQUARED) {
            Vec3 forward = horizontalMovement.normalize();
            Vec3 right = new Vec3(forward.z, 0.0, -forward.x);

            desiredPosition = playerPosition
                .subtract(forward.scale(TRAIL_DISTANCE))
                .add(right.scale(SIDE_OFFSET))
                .add(0.0, HEIGHT_OFFSET, 0.0);
        } else {
            // Keep X/Z fixed while idle, but follow vertical movement such as jumping.
            desiredPosition = new Vec3(
                desiredPosition.x,
                playerPosition.y + HEIGHT_OFFSET,
                desiredPosition.z
            );
        }
    }

    /**
     * Critically damped-style spring motion with a speed cap and a long-distance
     * recovery threshold. This avoids the jitter produced by directly lerping
     * the rendered entity toward a new target every tick.
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

        Vec3 acceleration = displacement.scale(FOLLOW_SPRING)
            .subtract(followVelocity.scale(FOLLOW_DAMPING));
        followVelocity = followVelocity.add(acceleration);

        double speed = followVelocity.length();
        if (speed > MAX_FOLLOW_SPEED) {
            followVelocity = followVelocity.scale(MAX_FOLLOW_SPEED / speed);
        }

        smoothedPosition = smoothedPosition.add(followVelocity);

        if (displacement.lengthSqr() < ARRIVAL_DISTANCE * ARRIVAL_DISTANCE
            && followVelocity.lengthSqr() < 0.0004) {
            smoothedPosition = desiredPosition;
            followVelocity = Vec3.ZERO;
        }
    }

    private static void createAvatar(ClientLevel level, Vec3 playerPosition, float playerYaw) {
        clearAvatar();
        avatar = new Allay(EntityType.ALLAY, level);
        avatar.setNoAi(true);
        avatar.setNoGravity(true);
        avatar.setSilent(true);
        avatarLevel = level;

        // Spawn beside and slightly ahead of the player so the first summon is visible.
        double yawRadians = Math.toRadians(playerYaw);
        Vec3 forward = new Vec3(-Math.sin(yawRadians), 0.0, Math.cos(yawRadians));
        Vec3 right = new Vec3(Math.cos(yawRadians), 0.0, Math.sin(yawRadians));

        desiredPosition = playerPosition
            .add(right.scale(SIDE_OFFSET))
            .add(forward.scale(INITIAL_FORWARD_OFFSET))
            .add(0.0, HEIGHT_OFFSET, 0.0);
        smoothedPosition = desiredPosition;
        followVelocity = Vec3.ZERO;
        previousPlayerPosition = playerPosition;

        avatar.setPos(smoothedPosition.x, smoothedPosition.y, smoothedPosition.z);
    }

    private static void clearAvatar() {
        avatar = null;
        avatarLevel = null;
        desiredPosition = null;
        smoothedPosition = null;
        followVelocity = Vec3.ZERO;
        previousPlayerPosition = null;
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
