import base64
import json
import os
import tempfile
import time
from enum import Enum
from pathlib import Path
from urllib.request import Request, urlopen

import bpy

bl_info = {
    "name": "Text To CAD",
    "description": "Generate an solid object from text, using Zoo.dev",
    "author": "Zoo.dev",
    "version": (1, 0),
    "blender": (3, 0, 0),
    "location": "3D Viewport > Object Mode > Add > Text To CAD",
    "warning": "",  # used for warning icon and text in addons panel
    "doc_url": "https://github.com/KittyCAD/text-to-cad-blender-plugin",
    "tracker_url": "https://github.com/KittyCAD/text-to-cad-blender-plugin/issues",
    "support": "COMMUNITY",
    "category": "Add Mesh",
}


def import_fbx(path: Path) -> None:
    bpy.ops.import_scene.fbx(filepath=str(path))


def import_glb(path: Path) -> None:
    bpy.ops.import_scene.gltf(filepath=str(path))


def import_obj(path: Path) -> None:
    bpy.ops.wm.obj_import(filepath=str(path))


def import_ply(path: Path) -> None:
    bpy.ops.wm.ply_import(filepath=str(path))


def import_stl(path: Path) -> None:
    bpy.ops.import_mesh.stl(filepath=str(path))


class OutputFormat(Enum):
    # define an enum class to hold some mappings
    # the following format is required for items in an Enum property
    # (identifier, name, description, icon, number)
    fbx = {"func": import_fbx, "format": ("fbx", "fbx", "", "", 0)}
    glb = {"func": import_glb, "format": ("glb", "glb", "", "", 1)}
    gltf = {"func": import_glb, "format": ("gltf", "gltf", "", "", 2)}
    obj = {"func": import_obj, "format": ("obj", "obj", "", "", 3)}
    ply = {"func": import_ply, "format": ("ply", "ply", "", "", 4)}
    stl = {"func": import_stl, "format": ("stl", "stl", "", "", 5)}


def import_file(path: Path, output_format: str) -> None:
    # generic import function, get the correct function from output mapping
    func = OutputFormat[output_format].value["func"]
    func(path)


def call_zoo_api(prompt: str, output_format: str, output_dir: Path) -> Path | str:
    # define the url for the POST request
    post_url = f"https://api.zoo.dev/ai/text-to-cad/{output_format}"

    # define the authorization string
    auth = f"Bearer {os.environ['KITTYCAD_API_TOKEN']}"

    # create the json data string which contains our text prompt
    data = json.dumps({"prompt": prompt}).encode("utf-8")

    # define headers
    # the User-Agent header is necessary to prevent an HTTP 403 error
    headers = {
        "Authorization": auth,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }

    # create the response
    req = Request(post_url, data=data, headers=headers)

    with urlopen(req) as response:
        # decode the response to a dict
        result = json.loads(response.read().decode("utf-8"))

    # get the id of the request
    op_id = result["id"]

    # the requests are made asynchronously so keep checking the operations via the id
    # https://zoo.dev/docs/api/api-calls/get-an-async-operation
    while result["status"] not in ["completed", "failed"]:
        async_url = f"https://api.zoo.dev/async/operations/{op_id}"
        headers = {"Authorization": auth, "User-Agent": "Mozilla/5.0"}
        async_req = Request(async_url, headers=headers)
        with urlopen(async_req) as response:
            result = json.loads(response.read().decode("utf-8"))
        # using a sleep so that we don't keep pinging the site and get rate limited
        time.sleep(10)

    if result["status"] == "completed":
        # get the base64 encoded string of the output
        outputs = result["outputs"][f"source.{output_format}"]

        # this seems strange I have to do this. See the official kittycad implementation
        # https://github.com/KittyCAD/kittycad.py/blob/main/kittycad/models/base64data.py#L39
        decoded = base64.urlsafe_b64decode(outputs.strip("=") + "===")

        # save contents to a file on disk at the users location
        fp = output_dir / f"{op_id}.{output_format}"
        with open(fp, "wb") as out:
            out.write(decoded)

        return fp

    if result["status"] == "failed":
        # we've not generated an object for some reason
        # return the error string
        return result["error"]


def check_for_token() -> bool:
    return "KITTYCAD_API_TOKEN" in os.environ


class TextToCAD(bpy.types.Operator):
    """Text To CAD using Zoo.dev"""

    bl_idname = "text_to_cad.send"
    bl_label = "Text To CAD"
    bl_description = "Generate a solid object from text. This may take several minutes to run"
    bl_options = {"REGISTER", "UNDO"}

    # tracking number of instances and invocation
    instances = 0
    invoked = False

    # get the home path of the user
    home_path = str(Path.home())

    def setter_getter(name: str):
        return {
            "get": lambda self: getattr(bpy.context.scene.selected_dir, name),
            "set": lambda self, value: setattr(
                bpy.context.scene.selected_dir, name, value
            ),
        }

    # create a text property for prompt entry
    text: bpy.props.StringProperty(
        name="Text Prompt",
        default="Create a 2m by 2m plate with 4 holes and rounded corners.",
        description="Describe an object that can be represented in geometric shapes.",
        **setter_getter("text"),
    )

    # create a dropdown menu for output selection
    output_format: bpy.props.EnumProperty(
        items=[i.value["format"] for i in OutputFormat],
        name="Output Format",
        default=5,
        description="Select from the possible output formats to save the file to disk",
    )

    def get_output_dir(self):
        return bpy.context.scene.selected_dir.output_dir

    def set_output_dir(self, value):
        props = bpy.context.scene.selected_dir
        props.output_dir = value
        if TextToCAD.instances != 0 or not TextToCAD.invoked:
            return
        TextToCAD.instances += 1
        bpy.ops.text_to_cad.send(
            "INVOKE_DEFAULT",
            text=props.text,
            output_format=props.output_format,
            output_dir=props.output_dir,
        )
        TextToCAD.instances -= 1
        TextToCAD.invoked = False

    # create a folder selection menu option
    output_dir: bpy.props.StringProperty(
        name="Output Directory",
        default=home_path,
        description="Select a directory to save the generated CAD file",
        subtype="DIR_PATH",
        maxlen=1024,
        get=get_output_dir,
        set=set_output_dir,
    )

    def execute(self, _context) -> set:
        # check if the user has an API token
        if not check_for_token():
            msg = """Could not find the environment variable 'KITTYCAD_API_TOKEN', 
            please proceed to https://zoo.dev/account to setup your account. 
            If you already have an account, create an API token at https://zoo.dev/account/api-tokens"""
            self.report({"ERROR"}, msg)

            # exit with a cancelled status
            return {"CANCELLED"}

        self.report({"INFO"}, "Calling the Text To CAD API, this may take a while...")

        # set the output dir. Blender will set relative paths to current .blend file
        self.output_dir = os.path.realpath(bpy.path.abspath(self.output_dir))

        # call the Zoo API
        text_to_cad_output = call_zoo_api(
            self.text, self.output_format, Path(self.output_dir)
        )

        if isinstance(text_to_cad_output, Path):
            # if we get a path object back, a file was created. Notify the user and import
            self.report({"INFO"}, f"Output file saved to {str(text_to_cad_output)}")
            import_file(text_to_cad_output, self.output_format)
        else:
            # failed generation, report error to user
            self.report({"ERROR"}, text_to_cad_output)

        TextToCAD.invoked = False
        return {"FINISHED"}

    def invoke(self, context, _event):
        TextToCAD.invoked = True
        res = context.window_manager.invoke_props_dialog(self, width=600)
        return res


class TextToCADProps(bpy.types.PropertyGroup):
    # the implementation for the folder browser is using methods described here:
    # https://blender.stackexchange.com/a/295298

    home_path = str(Path.home())

    text: bpy.props.StringProperty(
        name="Text Prompt",
        default="Create a 2m by 2m plate with 4 holes and rounded corners.",
        description="Describe an object that can be represented in geometric shapes.",
    )

    # create a dropdown menu for output selection
    output_format: bpy.props.EnumProperty(
        items=[i.value["format"] for i in OutputFormat],
        name="Output Format",
        default=5,
    )

    # create a folder selection menu
    output_dir: bpy.props.StringProperty(
        name="Output Directory",
        default=home_path,
        description="Select a directory to save the generated CAD file",
        subtype="DIR_PATH",
        maxlen=1024,
    )


def create_icon() -> str:
    im_str = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10\x00\x00\x00\x10\x08\x06\x00\x00\x00\x1f\xf3\xffa\x00\x00\x01\xa5IDATx\x9c\xcd\x921o\xda`\x10\x86\x9f\xcf\xfe\x0cb\x01\x04(\xa9m\x02\x12\x9d\x91\xd2!l\xccl\xcd\xc0\x8e\xd4\xfc\x06\xd4H\xf0\x17J26S\xca\xd6\x0c\x8d\x9a\x01\x98\x92\x89\xcd\xe2\x174#\x12\x8c!\x02!0\xb6\xaf\x03\n\xa2j\xa7fh\xdf\xe9\x86\xbb\xe7N\xef{\xcav\x1c\xe1\x152^3\xfc\x9f\x01\xa2("\x8a"D\x04\x91\xad-a\x18\x12E\x11\xfb=a\x18\xfe\x0e0M\x93l6K&\x93!\x16\x8b\x11\x8f\xc7\t\x82\x00\xd7uI&\x93\x84a\x88\xef\xfb\xa4\xd3il\xdb\xde-\x02\xd0\x9b\xcd\x86b\xb1\xc8E\xa7\x83R\n\xad5\xddn\x97r\xb9L\xa5Ra4\x1a\xf1\xa9\xd3\xa1rrB\xb3\xd9d6\x9bqqy\x89\xe7y\xdb\x13l\xc7\x117\x9f\x97B\xb1(\x9f\xaf\xae\xe4\xdb\xed\xad|8;\x93\xe1p(\x8e\xebJ\xbd^\x97~\xbf/\x9e\xe7\xc9\xfb\xd3S\xc9\x1f\x1d\xc9\xfd\xc3\x83T\xabU\xc9\x1d\x1c\x88\x01\xb0^\xafi4\x1a\xbc;>\xa6\xddn\xa3\x94b<\x1e\xb3Z\xad(\x14\n$\x12\tf\xcf\xcfL\xa7SR\xa9\x14o\x0e\x0f\xb7\xde\x88\xa0\x83 \xa0T*Q\xab\xd5\x10\x11\xbe\\_\xf3\xf5\xe6\x86\xc1`@\xaf\xd7C\x9b&\x1f\xcf\xcfY,\x16\xb4Z-\xde\x96J|\xbf\xbb\xe3\xc7\xe3#\x96e\xa1l\xc7\x11\xad5J)\xe2\xf18Zk\x96\xcb%\xbe\xefc\xdb6OOO\xcc\xe7s\x0c\xc3 \x97\xcb\xa1\xb5f2\x99`Y\x16\xc0\x16\x00\xfc\x12\x9fR\n\xa5\x14a\x18\xa2\x94\xc20\x8c]\x8c"\x82i\x9a\xbb\x18\xf5K\xf12\xb4\xaf\xfdF`\x07\xfa\xe3#\xfd\xad\xfe=\xe0\'\xb2\x8a\xb2\xa5\'B\xe7\xea\x00\x00\x00\x00IEND\xaeB`\x82'
    with tempfile.NamedTemporaryFile(
        mode="w+b", prefix="zoo-icon-", suffix=".png", delete=False
    ) as fp:
        fp.write(im_str)
        return fp.name


def menu_func(self, _context):
    # add a separator to the menu before adding our addon
    pcoll = preview_collections["main"]
    my_icon = pcoll["my_icon"]
    self.layout.separator()
    self.layout.operator(TextToCAD.bl_idname, icon_value=my_icon.icon_id)


# store keymaps here to access after registration
addon_keymaps = []

# We can store multiple preview collections here,
# however in this example we only store "main"
preview_collections = {}


def register():
    # Note that preview collections returned by bpy.utils.previews
    # are regular py objects - you can use them to store custom data.
    import bpy.utils.previews

    pcoll = bpy.utils.previews.new()

    icon = create_icon()

    # load a preview thumbnail of a file and store in the previews collection
    pcoll.load("my_icon", icon, "IMAGE")

    preview_collections["main"] = pcoll

    # register classes and add to menu
    bpy.utils.register_class(TextToCAD)
    bpy.utils.register_class(TextToCADProps)
    bpy.types.VIEW3D_MT_add.append(menu_func)
    bpy.types.Scene.selected_dir = bpy.props.PointerProperty(type=TextToCADProps)

    # handle the keymap
    wm = bpy.context.window_manager
    # Note that in background mode (no GUI available), keyconfigs are not available either,
    # so we have to check this to avoid nasty errors in background case.
    kc = wm.keyconfigs.addon
    if kc:
        km = wm.keyconfigs.addon.keymaps.new(name="Object Mode", space_type="EMPTY")
        kmi = km.keymap_items.new(
            TextToCAD.bl_idname, "T", "PRESS", ctrl=True, shift=True
        )
        addon_keymaps.append((km, kmi))


def unregister():
    for pcoll in preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    preview_collections.clear()

    # Note: when unregistering, it's usually good practice to do it in reverse order you registered.
    # Can avoid strange issues like keymap still referring to operators already unregistered...
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    # unregister and remove from menus
    bpy.utils.unregister_class(TextToCAD)
    bpy.utils.unregister_class(TextToCADProps)
    bpy.types.VIEW3D_MT_add.remove(menu_func)
    del bpy.types.Scene.selected_dir


# This allows you to run the script directly from Blender's Text editor
# to test the add-on without having to install it.
if __name__ == "__main__":
    register()
