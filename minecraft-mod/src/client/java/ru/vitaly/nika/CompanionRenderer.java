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
    private static final double SIDE_OFFSET = 0.95;
    private static final double FORWARD_OFFSET = -0.25;
    private static final double HEIGHT_OFFSET = 1.15;
    private static final double FOLLOW_SMOOTHING = 0.24;
    private static final double BOB_AMPLITUDE = 0.07;
    private static final double BOB_SPEED = 0.10;

    private static boolean enabled;
    private static Allay avatar;
    private static ClientLevel avatarLevel;
    private static Vec3 smoothedPosition;

    private CompanionRenderer() {
    }

    static void initialize() {
        ClientTickEvents.END_CLIENT_TICK.register(CompanionRenderer::tick);
        WorldRenderEvents.AFTER_ENTITIES.register(CompanionRenderer::render);
    }

    static boolean isEnabled() {
        return enabled;
    }

    static void setEnabled(boolean value) {
        enabled = value;
        if (!value) {
            clearAvatar();
        }
    }

    private static void tick(Minecraft client) {
        if (!enabled || client.player == null || client.level == null) {
            clearAvatar();
            return;
        }

        if (avatar == null || avatarLevel != client.level) {
            createAvatar(client.level);
        }

        var player = client.player;
        double yawRadians = Math.toRadians(player.getYRot());

        // Minecraft yaw 0 faces +Z. This vector points to the player's right.
        Vec3 right = new Vec3(Math.cos(yawRadians), 0.0, Math.sin(yawRadians));
        Vec3 forward = new Vec3(-Math.sin(yawRadians), 0.0, Math.cos(yawRadians));

        double bob = Math.sin(client.level.getGameTime() * BOB_SPEED) * BOB_AMPLITUDE;
        Vec3 target = player.position()
            .add(right.scale(SIDE_OFFSET))
            .add(forward.scale(FORWARD_OFFSET))
            .add(0.0, HEIGHT_OFFSET + bob, 0.0);

        smoothedPosition = smoothedPosition == null
            ? target
            : smoothedPosition.lerp(target, FOLLOW_SMOOTHING);

        // Preserve the previous transform so the vanilla renderer can interpolate.
        avatar.setOldPosAndRot();
        avatar.setPos(smoothedPosition.x, smoothedPosition.y, smoothedPosition.z);
        avatar.tickCount++;

        double dx = player.getX() - smoothedPosition.x;
        double dz = player.getZ() - smoothedPosition.z;
        float facingYaw = (float) (Math.atan2(dz, dx) * (180.0 / Math.PI)) - 90.0F;
        avatar.setYRot(facingYaw);
    }

    private static void createAvatar(ClientLevel level) {
        clearAvatar();
        avatar = new Allay(EntityType.ALLAY, level);
        avatar.setNoAi(true);
        avatar.setNoGravity(true);
        avatar.setSilent(true);
        avatarLevel = level;
    }

    private static void clearAvatar() {
        avatar = null;
        avatarLevel = null;
        smoothedPosition = null;
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
