Render a module's HTML block directly into the chat during your turn.

Use this when a module has a purpose-built visual or interactive block that
communicates a result better than prose — for example a form, a status panel, or
a data view. Pass the module name, the block basename, and a JSON `props` object
with the data the block needs. The block is persisted to the conversation and
survives reload.

Do not invent module or block names. If the named block does not exist the tool
returns an error; render only blocks you know the module provides.
