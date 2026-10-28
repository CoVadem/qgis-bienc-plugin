# Define the stroke color (dark blue)
stroke_color = QColor(16, 16, 32)  # Dark blue
stroke_width = 0.06
invalid_color = QColor(255, 0, 255) # Purple

def browse_folder():
    """ Open a folder browsing dialog in QGIS and return the selected folder path. """
    folder = QFileDialog.getExistingDirectory(None, "Select Directory")
    if folder:
        print(f"Selected folder: {folder}")
        return folder
    else:
        print("No folder selected.")
        return None
        
def create_symbol(layer, color):
    symbol = QgsSymbol.defaultSymbol(layer.geometryType())
    symbol.setColor(color)  # Color interpolated from the ramp

    # Configure stroke for all symbols if it's a fill symbol
    if isinstance(symbol, QgsFillSymbol):
        for layer2 in symbol.symbolLayers():
            if isinstance(layer2, QgsSimpleFillSymbolLayer):
                layer2.setStrokeColor(stroke_color)
                layer2.setStrokeWidth(stroke_width)  # Set stroke width if needed
                
    return symbol

def apply_default_blue_gradient(layer, field='DRVAL1', min_val=0, max_val=7, intervals=14):
    # Fetch the default blue color ramp from QGIS style
    default_style = QgsStyle.defaultStyle()
    color_ramp = default_style.colorRamp('Blues')

    # Calculate the range increment
    range_size = (max_val - min_val) / intervals
    ranges = []
    
    lower_bound = -10
    upper_bound = 0
    symbol = create_symbol(layer, invalid_color)
    ranges.append(QgsRendererRange(lower_bound, upper_bound, symbol, f"{lower_bound:.1f} - {upper_bound:.1f}"))
    
    # Create ranges and corresponding symbols
    for i in range(intervals):            
        lower_bound = min_val + i * range_size
        upper_bound = lower_bound + range_size
        symbol = create_symbol(layer, color_ramp.color(i / intervals))
        ranges.append(QgsRendererRange(lower_bound, upper_bound, symbol, f"{lower_bound:.1f} - {upper_bound:.1f}"))

    lower_bound = max_val
    upper_bound = max_val * 10
    symbol = create_symbol(layer, color_ramp.color(1))
    ranges.append(QgsRendererRange(lower_bound, upper_bound, symbol, f"{lower_bound:.1f} - {upper_bound:.1f}"))

    # Create and set the graduated renderer
    renderer = QgsGraduatedSymbolRenderer(field, ranges)
    renderer.setSourceColorRamp(color_ramp)
    renderer.setMode(QgsGraduatedSymbolRenderer.Custom)
    layer.setRenderer(renderer)
        
def add_s57_files(folder_path):
    # Create a layer group in the layer tree with the name of the last folder in the path
    root = QgsProject.instance().layerTreeRoot()
    layer_group = root.insertGroup(0, folder_path)

    for filename in os.listdir(folder_path):
        if filename.endswith('.000'):
            file_path = os.path.join(folder_path, filename)
            # Load the .000 file as a vector layer
            vlayer = QgsVectorLayer(file_path, filename, "ogr")
            if not vlayer.isValid():
                print(f"Failed to load file: {filename}")
                continue
            
            print(f"Processing file: {filename}")
            sublayers = vlayer.dataProvider().subLayers()
            for sublayer_info in sublayers:
                if '!!DEPARE!!' in sublayer_info:
                    uri = f"{file_path}|layername=DEPARE"
                    depare_layer = QgsVectorLayer(uri, f"{filename} - DEPARE", "ogr")
                    if depare_layer.isValid():
                        apply_default_blue_gradient(depare_layer)
                        QgsProject.instance().addMapLayer(depare_layer, False)
                        # Add the layer to the created group
                        layer_group.addLayer(depare_layer)
                        print(f"Added DEPARE layer from {filename}")
                        
                    else:
                        print(f"Failed to load DEPARE layer from {filename}")



# Run the function
folder_path = browse_folder()
if folder_path:
    add_s57_files(folder_path)
