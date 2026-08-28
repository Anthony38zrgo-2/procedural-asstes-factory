# Montañas procedurales

Unidad mínima para regenerar las montañas 3D actuales de La Chutana sin depender de Formula90s.

## Contenido

- `inputs/la_chutana/la_chutana_topo.svg`: fuente semántica de elevación del circuito.
- `tools/generate_topo_terrain.py`: generador principal; produce los anillos Near/Far, el domo, la textura, el manifest y el reporte.
- `tools/generate_mountain_texture.py`: genera la textura procedural usada por los anillos.
- `tools/build_semantic_topo_svg_v3.py`: permite reconstruir o modificar el SVG topográfico base.
- `assets/la_chutana/`: salida actual de referencia, incluidos los tres GLB.
- `build_la_chutana.ps1`: comando reproducible desde cualquier directorio.
- `requirements.txt`: dependencias Python mínimas.

## Generar

Desde `D:\procedural-asstes-factory\procedural\mountains`:

```powershell
python -m pip install -r requirements.txt
.\build_la_chutana.ps1
```

Para reconstruir primero el SVG semántico:

```powershell
python .\tools\build_semantic_topo_svg_v3.py .\inputs\la_chutana\la_chutana_topo.svg
.\build_la_chutana.ps1
```

La generación reemplaza solamente el contenido de `assets/la_chutana`. Git conserva el rollback del asset y sus fuentes mediante el commit correspondiente.

## GLB actuales

- `far_mountains_ring.glb`: anillo lejano.
- `near_mountains_ring.glb`: anillo cercano.
- `sky_dome.glb`: domo del cielo usado por el mismo sistema.

No se copiaron scripts de runtime de Godot, pruebas del juego ni el Track Builder/editor.
