# -*- coding: utf-8 -*-

bl_info = {
    "name": "Iterative Baker",
    "description": "Automate Cycles iterative baking with progress bar and cancellation support",
    "author": "Generated",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "Render Properties > Iterative Baker",
    "category": "Render",
}

import bpy


# ===================================================================
# Helpers
# ===================================================================

def _state_clear(wm):
    """Remove all iterative-baker custom properties from the window manager."""
    for key in ("iterative_baker_running",
                "iterative_baker_cancel",
                "iterative_baker_current",
                "iterative_baker_total"):
        try:
            del wm[key]
        except KeyError:
            pass


def _state_init(wm, total):
    """Set properties for a fresh run."""
    wm['iterative_baker_running'] = True
    wm['iterative_baker_cancel'] = False
    wm['iterative_baker_current'] = 0
    wm['iterative_baker_total'] = total


# ===================================================================
# Scene property
# ===================================================================

def _iterations_update(self, context):
    if self.iterative_baker_iterations < 1:
        self.iterative_baker_iterations = 1
    elif self.iterative_baker_iterations > 10000:
        self.iterative_baker_iterations = 10000


# ===================================================================
# Operator: main bake loop
# ===================================================================

class ITERATIVEBAKER_OT_bake(bpy.types.Operator):
    """Run repeated Cycles bakes automatically"""

    bl_idname = "iterative_baker.bake"
    bl_label = "Start Iterative Baking"
    bl_description = "Bake repeatedly for the configured number of iterations"

    _timer = None
    _baking = False

    @classmethod
    def poll(cls, context):
        if context.window_manager.get("iterative_baker_running"):
            return False
        obj = context.active_object
        return (
            obj is not None
            and obj.type == 'MESH'
            and context.mode == 'OBJECT'
        )

    # ------------------------------------------------------------------
    def invoke(self, context, event):
        wm = context.window_manager
        scene = context.scene

        obj = context.active_object
        if obj is None:
            self.report({'ERROR'}, "No active object selected")
            return {'CANCELLED'}
        if obj.type != 'MESH':
            self.report({'ERROR'}, "Active object must be a mesh")
            return {'CANCELLED'}

        total = scene.iterative_baker_iterations
        if total < 1:
            self.report({'ERROR'}, "Iterations must be at least 1")
            return {'CANCELLED'}

        # initialise shared state
        _state_init(wm, total)
        wm.progress_begin(0, total)
        wm.progress_update(0)

        self._timer = wm.event_timer_add(0.1, window=context.window)
        self._baking = False
        wm.modal_handler_add(self)

        self.report({'INFO'}, f"Starting {total} iteration(s) …")
        return {'RUNNING_MODAL'}

    # ------------------------------------------------------------------
    def modal(self, context, event):
        wm = context.window_manager

        if event.type == 'ESC' and event.value == 'PRESS':
            self._cancel(context, "Cancelled (ESC)")
            return {'CANCELLED'}

        if wm.get("iterative_baker_cancel"):
            self._cancel(context, "Cancelled")
            return {'CANCELLED'}

        if event.type == 'TIMER':
            return self._on_timer(context)

        return {'PASS_THROUGH'}

    # ------------------------------------------------------------------
    def _on_timer(self, context):
        wm = context.window_manager

        if wm.get("iterative_baker_cancel"):
            self._cancel(context, "Cancelled")
            return {'CANCELLED'}

        if self._baking:          # still inside previous bake call
            return {'RUNNING_MODAL'}

        current = wm['iterative_baker_current']
        total = wm['iterative_baker_total']

        if current >= total:
            self._finish(context)
            return {'FINISHED'}

        # --- single bake iteration ---
        self._baking = True
        try:
            # EXEC_DEFAULT runs synchronously without popping up extra UI.
            bpy.ops.object.bake('EXEC_DEFAULT')
        except RuntimeError as exc:
            self._baking = False
            self._cancel(context, f"Bake error: {exc}")
            self.report({'ERROR'},
                        f"Bake failed at iteration {current + 1}: {exc}")
            return {'CANCELLED'}

        self._baking = False

        wm['iterative_baker_current'] = current + 1
        wm.progress_update(current + 1)

        return {'RUNNING_MODAL'}

    # ------------------------------------------------------------------
    def _finish(self, context):
        wm = context.window_manager
        total = wm['iterative_baker_total']
        self._teardown(context)
        self.report({'INFO'}, f"Iterative baking complete ({total} iterations)")

    def _cancel(self, context, reason=""):
        wm = context.window_manager
        cur = wm.get("iterative_baker_current", 0)
        total = wm.get("iterative_baker_total", 0)
        self._teardown(context)
        msg = f"Stopped at {cur}/{total}"
        if reason:
            msg += f"  –  {reason}"
        self.report({'INFO'}, msg)

    def _teardown(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.progress_end()
        _state_clear(wm)
        self._baking = False


# ===================================================================
# Operator: cancel button
# ===================================================================

class ITERATIVEBAKER_OT_cancel(bpy.types.Operator):
    """Signal the running baker to stop gracefully"""

    bl_idname = "iterative_baker.cancel"
    bl_label = "Cancel Baking"
    bl_description = "Stop after the current iteration completes"

    def execute(self, context):
        context.window_manager['iterative_baker_cancel'] = True
        return {'FINISHED'}


# ===================================================================
# Panel
# ===================================================================

class ITERATIVEBAKER_PT_panel(bpy.types.Panel):
    """Panel in Render Properties – only visible when Cycles is active"""

    bl_label = "Iterative Baker"
    bl_idname = "ITERATIVEBAKER_PT_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"

    @classmethod
    def poll(cls, context):
        return context.scene.render.engine == 'CYCLES'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        wm = context.window_manager
        running = wm.get("iterative_baker_running", False)

        layout.use_property_split = True
        layout.use_property_decorate = False

        # --- iterations setting ---
        col = layout.column(align=True)
        col.enabled = not running
        col.prop(scene, "iterative_baker_iterations")

        # --- action buttons ---
        row = layout.row(align=True)
        if not running:
            row.operator("iterative_baker.bake", text="Start Baking",
                         icon='RENDER_STILL')
        else:
            row.operator("iterative_baker.cancel", text="Cancel", icon='X')
            sub = row.row()
            sub.enabled = False
            sub.operator("iterative_baker.bake", text="Running…")

        # --- live progress ---
        if running:
            layout.separator()
            current = wm.get("iterative_baker_current", 0)
            total = wm.get("iterative_baker_total", scene.iterative_baker_iterations)
            pct = min(current / max(total, 1), 1.0)

            # text
            layout.label(
                text=f"Iteration {current} / {total}  ({pct * 100:.0f} %)",
                icon='TIME',
            )

            # cheap visual bar using a row of icons
            bar = layout.row(align=True)
            bar.scale_y = 0.6
            BAR_LEN = 40
            filled = int(round(pct * BAR_LEN))
            for i in range(BAR_LEN):
                icon = 'SOLID' if i < filled else 'BLANK1'
                bar.label(text="", icon=icon)


# ===================================================================
# Registration
# ===================================================================

classes = (
    ITERATIVEBAKER_OT_bake,
    ITERATIVEBAKER_OT_cancel,
    ITERATIVEBAKER_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.iterative_baker_iterations = bpy.props.IntProperty(
        name="Iterations",
        description="Number of bake iterations to perform",
        default=200,
        min=1,
        max=10000,
        update=_iterations_update,
    )


def unregister():
    del bpy.types.Scene.iterative_baker_iterations

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
