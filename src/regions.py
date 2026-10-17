"""regions.py - Venezuela's 25 first-level regions: the names our data uses and the
ISO 3166-2 codes the apps' maps use (geoBoundaries VEN ADM1 `shapeISO`).
"""

# model region name (lowercase, as IODA spells it) -> (ISO code, display name)
REGIONS = {
    "distrito capital": ("VE-A", "Distrito Capital"),
    "anzoátegui": ("VE-B", "Anzoátegui"),
    "apure": ("VE-C", "Apure"),
    "aragua": ("VE-D", "Aragua"),
    "barinas": ("VE-E", "Barinas"),
    "bolívar": ("VE-F", "Bolívar"),
    "carabobo": ("VE-G", "Carabobo"),
    "cojedes": ("VE-H", "Cojedes"),
    "falcón": ("VE-I", "Falcón"),
    "guárico": ("VE-J", "Guárico"),
    "lara": ("VE-K", "Lara"),
    "mérida": ("VE-L", "Mérida"),
    "miranda": ("VE-M", "Miranda"),
    "monagas": ("VE-N", "Monagas"),
    "nueva esparta": ("VE-O", "Nueva Esparta"),
    "portuguesa": ("VE-P", "Portuguesa"),
    "sucre": ("VE-R", "Sucre"),
    "táchira": ("VE-S", "Táchira"),
    "trujillo": ("VE-T", "Trujillo"),
    "yaracuy": ("VE-U", "Yaracuy"),
    "zulia": ("VE-V", "Zulia"),
    "dependencias federales": ("VE-W", "Dependencias Federales"),
    "vargas": ("VE-X", "La Guaira"),  # IODA still uses the pre-2019 name
    "delta amacuro": ("VE-Y", "Delta Amacuro"),
    "amazonas": ("VE-Z", "Amazonas"),
}

# ISO code -> (model region name, display name)
BY_ISO = {iso: (key, name) for key, (iso, name) in REGIONS.items()}
