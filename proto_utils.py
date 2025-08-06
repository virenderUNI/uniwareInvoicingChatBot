def normalize_gemini_args(data):
    """
    Recursively converts Gemini tool call args (MapComposite, Value, etc.) to plain Python dict/list.
    """
    # dict-like or MapComposite
    if isinstance(data, dict) or hasattr(data, "items"):
        return {k: normalize_gemini_args(v) for k, v in data.items()}

    # List or ListValue
    if isinstance(data, list) or hasattr(data, "__iter__") and not isinstance(data, str):
        return [normalize_gemini_args(v) for v in data]

    # Value wrappers
    if hasattr(data, "struct_value"):
        return normalize_gemini_args(data.struct_value.fields)

    if hasattr(data, "list_value"):
        return [normalize_gemini_args(v) for v in data.list_value.values]

    if hasattr(data, "string_value"):
        return data.string_value

    if hasattr(data, "number_value"):
        return data.number_value

    if hasattr(data, "bool_value"):
        return data.bool_value

    if hasattr(data, "null_value"):
        return None

    if hasattr(data, "value"):  # Protobuf Value wrapper
        return normalize_gemini_args(data.value)

    return data
