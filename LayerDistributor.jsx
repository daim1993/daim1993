/* 
  Layer Distributor — dockable UI for arranging selected layers
  Shapes: Grid, Circle, Ellipse, Line, Spiral
  v1.0 — 2025-10-06
  Notes:
   • Works on 2D Position. 3D layers keep Z unchanged.
   • Order: “Selection” uses the order you clicked (top of selection is first).
   • “Index” uses layer index ascending in the comp.
*/

(function LayerDistributor(thisObj) {
  // ---------- Utilities ----------
  function getActiveComp() {
    var comp = app.project && app.project.activeItem;
    return (comp && comp instanceof CompItem) ? comp : null;
  }

  function getSelectedLayersOrdered(comp, orderMode) {
    var sel = comp.selectedLayers.slice(0); // copy
    if (sel.length < 1) return [];
    if (orderMode === 1) { // Index
      sel.sort(function(a, b){ return a.index - b.index; });
    } else { // Selection order (top of selection is first element)
      // AE already provides selection in click order for multiple selections (topmost clicked last).
      // Normalize to a stable order: top of selection = first to place.
      // Reverse so the timeline Z order doesn’t invert visuals.
      sel = sel.reverse();
    }
    return sel;
  }

  function deg2rad(d){ return d * Math.PI / 180.0; }

  function compCenter(comp) {
    return [comp.width/2, comp.height/2];
  }

  function clamp(v, lo, hi){ return Math.min(Math.max(v, lo), hi); }

  function withUndo(name, fn){
    app.beginUndoGroup(name);
    try { fn(); } finally { app.endUndoGroup(); }
  }

  // ---------- UI ----------
  function buildUI(thisObj) {
    var pal = (thisObj instanceof Panel) ? thisObj : new Window("palette", "Layer Distributor", undefined, {resizeable:true});

    // Root
    pal.orientation = "column";
    pal.alignChildren = ["fill","top"];
    pal.margins = 10;

    // Shape row
    var rowShape = pal.add("group");
    rowShape.add("statictext", undefined, "Shape:");
    var ddShape = rowShape.add("dropdownlist", undefined, ["Grid","Circle","Ellipse","Line","Spiral"]);
    ddShape.selection = 0;

    // Order + Center group
    var rowOpts = pal.add("group");
    rowOpts.orientation = "row";
    rowOpts.alignChildren = ["left","center"];

    var orderPanel = rowOpts.add("panel", undefined, "Order");
    orderPanel.orientation = "row";
    orderPanel.margins = 10;
    var rbSel = orderPanel.add("radiobutton", undefined, "Selection");
    var rbIdx = orderPanel.add("radiobutton", undefined, "Index");
    rbSel.value = true;

    var centerPanel = rowOpts.add("panel", undefined, "Origin");
    centerPanel.orientation = "row";
    centerPanel.margins = 10;
    var cbUseCompCenter = centerPanel.add("checkbox", undefined, "Use Comp Center");
    cbUseCompCenter.value = true;

    // Origin XY
    var originRow = pal.add("group");
    originRow.enabled = !cbUseCompCenter.value;
    originRow.add("statictext", undefined, "Origin X:");
    var etOriginX = originRow.add("edittext", undefined, "960");
    etOriginX.characters = 6;
    originRow.add("statictext", undefined, "Origin Y:");
    var etOriginY = originRow.add("edittext", undefined, "540");
    etOriginY.characters = 6;

    cbUseCompCenter.onClick = function(){
      originRow.enabled = !cbUseCompCenter.value;
    };

    // Parameter stacks (one shown at a time)
    var stack = pal.add("group");
    stack.orientation = "stack";
    stack.alignChildren = ["fill","top"];

    // --- GRID ---
    var gridGrp = stack.add("panel", undefined, "Grid");
    gridGrp.orientation = "column"; gridGrp.margins = 10;
    var g1 = gridGrp.add("group");
    g1.add("statictext", undefined, "Rows:");
    var etRows = g1.add("edittext", undefined, "3"); etRows.characters = 5;
    g1.add("statictext", undefined, "Cols:");
    var etCols = g1.add("edittext", undefined, "3"); etCols.characters = 5;

    var g2 = gridGrp.add("group");
    g2.add("statictext", undefined, "X Spacing:");
    var etGX = g2.add("edittext", undefined, "200"); etGX.characters = 6;
    g2.add("statictext", undefined, "Y Spacing:");
    var etGY = g2.add("edittext", undefined, "200"); etGY.characters = 6;

    var g3 = gridGrp.add("group");
    var cbFillByRow = g3.add("checkbox", undefined, "Fill by Row (else by Col)");
    cbFillByRow.value = true;

    // --- CIRCLE ---
    var circleGrp = stack.add("panel", undefined, "Circle");
    circleGrp.orientation = "column"; circleGrp.margins = 10;
    var c1 = circleGrp.add("group");
    c1.add("statictext", undefined, "Radius:");
    var etCR = c1.add("edittext", undefined, "300"); etCR.characters = 6;

    var c2 = circleGrp.add("group");
    c2.add("statictext", undefined, "Start Angle (deg):");
    var etCStart = c2.add("edittext", undefined, "0"); etCStart.characters = 6;
    var cbClockwise = c2.add("checkbox", undefined, "Clockwise");
    cbClockwise.value = false;

    // --- ELLIPSE ---
    var ellipseGrp = stack.add("panel", undefined, "Ellipse");
    ellipseGrp.orientation = "column"; ellipseGrp.margins = 10;
    var e1 = ellipseGrp.add("group");
    e1.add("statictext", undefined, "Radius X:");
    var etERx = e1.add("edittext", undefined, "400"); etERx.characters = 6;
    e1.add("statictext", undefined, "Radius Y:");
    var etERy = e1.add("edittext", undefined, "250"); etERy.characters = 6;

    var e2 = ellipseGrp.add("group");
    e2.add("statictext", undefined, "Start Angle (deg):");
    var etEStart = e2.add("edittext", undefined, "0"); etEStart.characters = 6;
    var cbEClockwise = e2.add("checkbox", undefined, "Clockwise");
    cbEClockwise.value = false;

    // --- LINE ---
    var lineGrp = stack.add("panel", undefined, "Line");
    lineGrp.orientation = "column"; lineGrp.margins = 10;
    var l1 = lineGrp.add("group");
    l1.add("statictext", undefined, "Start X:");
    var etLX1 = l1.add("edittext", undefined, "200"); etLX1.characters = 6;
    l1.add("statictext", undefined, "Start Y:");
    var etLY1 = l1.add("edittext", undefined, "200"); etLY1.characters = 6;

    var l2 = lineGrp.add("group");
    l2.add("statictext", undefined, "End X:");
    var etLX2 = l2.add("edittext", undefined, "1720"); etLX2.characters = 6;
    l2.add("statictext", undefined, "End Y:");
    var etLY2 = l2.add("edittext", undefined, "880"); etLY2.characters = 6;

    // --- SPIRAL (Archimedean) ---
    var spiralGrp = stack.add("panel", undefined, "Spiral");
    spiralGrp.orientation = "column"; spiralGrp.margins = 10;
    var s1 = spiralGrp.add("group");
    s1.add("statictext", undefined, "Turns:");
    var etTurns = s1.add("edittext", undefined, "2"); etTurns.characters = 6;

    var s2 = spiralGrp.add("group");
    s2.add("statictext", undefined, "Spacing (px/rev):");
    var etSpacing = s2.add("edittext", undefined, "250"); etSpacing.characters = 6;

    var s3 = spiralGrp.add("group");
    s3.add("statictext", undefined, "Start Angle (deg):");
    var etSStart = s3.add("edittext", undefined, "0"); etSStart.characters = 6;
    var cbSClockwise = s3.add("checkbox", undefined, "Clockwise");
    cbSClockwise.value = false;

    // --- Common jitter ---
    var jitterPanel = pal.add("panel", undefined, "Jitter (random offset)");
    jitterPanel.orientation = "row";
    jitterPanel.margins = 10;
    jitterPanel.add("statictext", undefined, "Jitter X:");
    var etJX = jitterPanel.add("edittext", undefined, "0"); etJX.characters = 5;
    jitterPanel.add("statictext", undefined, "Jitter Y:");
    var etJY = jitterPanel.add("edittext", undefined, "0"); etJY.characters = 5;

    // Buttons
    var btnRow = pal.add("group");
    btnRow.alignment = "right";
    var btnApply = btnRow.add("button", undefined, "Apply");
    var btnSnap = btnRow.add("button", undefined, "Snap to Origin");
    var btnAbout = btnRow.add("button", undefined, "?");

    // Stack switching
    function showPanel(ix){
      gridGrp.visible = (ix === 0);
      circleGrp.visible = (ix === 1);
      ellipseGrp.visible = (ix === 2);
      lineGrp.visible   = (ix === 3);
      spiralGrp.visible = (ix === 4);
    }
    showPanel(0);
    ddShape.onChange = function(){ showPanel(ddShape.selection.index); };

    // ---------- Placement engines ----------
    function randRange(a){ return (Math.random() * 2 - 1) * a; }

    function parseNum(uiElem, defVal){ var v = parseFloat(uiElem.text); return isNaN(v) ? defVal : v; }

    function resolveOrigin(comp){
      if (cbUseCompCenter.value) return compCenter(comp);
      return [parseNum(etOriginX, comp.width/2), parseNum(etOriginY, comp.height/2)];
    }

    function placeGrid(layers, comp) {
      var rows = Math.max(1, Math.floor(parseNum(etRows, 3)));
      var cols = Math.max(1, Math.floor(parseNum(etCols, 3)));
      var dx = parseNum(etGX, 200);
      var dy = parseNum(etGY, 200);
      var byRow = cbFillByRow.value;
      var origin = resolveOrigin(comp);
      var jitter = [parseNum(etJX,0), parseNum(etJY,0)];

      var total = layers.length;
      var maxCells = rows * cols;
      var useN = Math.min(total, maxCells);

      for (var i=0; i<useN; i++){
        var r, c;
        if (byRow) {
          r = Math.floor(i / cols);
          c = i % cols;
        } else {
          c = Math.floor(i / rows);
          r = i % rows;
        }
        var x = origin[0] + (c - (cols-1)/2) * dx + randRange(jitter[0]);
        var y = origin[1] + (r - (rows-1)/2) * dy + randRange(jitter[1]);

        var L = layers[i];
        if (L.property("Position")) {
          var pos = L.property("Position").value;
          if (L.threeDLayer) L.property("Position").setValue([x,y,pos[2]]);
          else L.property("Position").setValue([x,y]);
        }
      }
    }

    function placeCircle(layers, comp){
      var R = Math.max(0, parseNum(etCR, 300));
      var startDeg = parseNum(etCStart, 0);
      var cw = cbClockwise.value;
      var origin = resolveOrigin(comp);
      var jitter = [parseNum(etJX,0), parseNum(etJY,0)];

      var n = layers.length;
      if (n < 1) return;
      var step = 360 / n;
      for (var i=0; i<n; i++){
        var ang = startDeg + (cw ? -i*step : i*step);
        var rad = deg2rad(ang);
        var x = origin[0] + R * Math.cos(rad) + randRange(jitter[0]);
        var y = origin[1] + R * Math.sin(rad) + randRange(jitter[1]);
        var L = layers[i];
        if (L.property("Position")) {
          var pos = L.property("Position").value;
          if (L.threeDLayer) L.property("Position").setValue([x,y,pos[2]]);
          else L.property("Position").setValue([x,y]);
        }
      }
    }

    function placeEllipse(layers, comp){
      var Rx = Math.max(0, parseNum(etERx, 400));
      var Ry = Math.max(0, parseNum(etERy, 250));
      var startDeg = parseNum(etEStart, 0);
      var cw = cbEClockwise.value;
      var origin = resolveOrigin(comp);
      var jitter = [parseNum(etJX,0), parseNum(etJY,0)];

      var n = layers.length;
      if (n < 1) return;
      var step = 360 / n;
      for (var i=0; i<n; i++){
        var ang = startDeg + (cw ? -i*step : i*step);
        var rad = deg2rad(ang);
        var x = origin[0] + Rx * Math.cos(rad) + randRange(jitter[0]);
        var y = origin[1] + Ry * Math.sin(rad) + randRange(jitter[1]);
        var L = layers[i];
        if (L.property("Position")) {
          var pos = L.property("Position").value;
          if (L.threeDLayer) L.property("Position").setValue([x,y,pos[2]]);
          else L.property("Position").setValue([x,y]);
        }
      }
    }

    function placeLine(layers, comp){
      var x1 = parseNum(etLX1, 200), y1 = parseNum(etLY1, 200);
      var x2 = parseNum(etLX2, 1720), y2 = parseNum(etLY2, 880);
      var jitter = [parseNum(etJX,0), parseNum(etJY,0)];

      var n = layers.length;
      if (n < 1) return;
      for (var i=0; i<n; i++){
        var t = (n === 1) ? 0.0 : (i/(n-1));
        var x = x1 + (x2-x1)*t + randRange(jitter[0]);
        var y = y1 + (y2-y1)*t + randRange(jitter[1]);
        var L = layers[i];
        if (L.property("Position")) {
          var pos = L.property("Position").value;
          if (L.threeDLayer) L.property("Position").setValue([x,y,pos[2]]);
          else L.property("Position").setValue([x,y]);
        }
      }
    }

    function placeSpiral(layers, comp){
      // Archimedean: r = a + b*theta
      // spacing ≈ 2πb per revolution → b = spacing / (2π), a = 0
      var turns = Math.max(0.01, parseNum(etTurns, 2));
      var spacing = Math.max(0, parseNum(etSpacing, 250));
      var startDeg = parseNum(etSStart, 0);
      var cw = cbSClockwise.value;
      var origin = resolveOrigin(comp);
      var jitter = [parseNum(etJX,0), parseNum(etJY,0)];

      var n = layers.length;
      if (n < 1) return;
      var twoPI = Math.PI * 2;
      var totalTheta = turns * twoPI;
      var b = spacing / twoPI;
      var dir = cw ? -1 : 1;

      for (var i=0; i<n; i++){
        var t = (n===1) ? 0 : (i/(n-1));
        var theta = deg2rad(startDeg) + dir * (t * totalTheta);
        var r = b * (theta - deg2rad(startDeg)) * dir; // start at center
        var x = origin[0] + r * Math.cos(theta) + randRange(jitter[0]);
        var y = origin[1] + r * Math.sin(theta) + randRange(jitter[1]);

        var L = layers[i];
        if (L.property("Position")) {
          var pos = L.property("Position").value;
          if (L.threeDLayer) L.property("Position").setValue([x,y,pos[2]]);
          else L.property("Position").setValue([x,y]);
        }
      }
    }

    // ---------- Actions ----------
    btnApply.onClick = function(){
      var comp = getActiveComp();
      if (!comp) { alert("Open a composition."); return; }

      var orderMode = rbIdx.value ? 1 : 0;
      var layers = getSelectedLayersOrdered(comp, orderMode);
      if (layers.length < 1) { alert("Select at least one layer in the active comp."); return; }

      withUndo("Layer Distributor", function(){
        switch (ddShape.selection.index) {
          case 0: placeGrid(layers, comp); break;
          case 1: placeCircle(layers, comp); break;
          case 2: placeEllipse(layers, comp); break;
          case 3: placeLine(layers, comp); break;
          case 4: placeSpiral(layers, comp); break;
        }
      });
    };

    btnSnap.onClick = function(){
      var comp = getActiveComp();
      if (!comp) { alert("Open a composition."); return; }
      var origin = resolveOrigin(comp);
      var sel = comp.selectedLayers;
      if (sel.length < 1) { alert("Select layers to snap."); return; }
      withUndo("Snap to Origin", function(){
        for (var i=0;i<sel.length;i++){
          var L = sel[i];
          if (L.property("Position")) {
            var pos = L.property("Position").value;
            if (L.threeDLayer) L.property("Position").setValue([origin[0], origin[1], pos[2]]);
            else L.property("Position").setValue(origin);
          }
        }
      });
    };

    btnAbout.onClick = function(){
      alert("Layer Distributor\n• Grid / Circle / Ellipse / Line / Spiral\n• Origin: comp center or custom\n• Order: selection or index\n• Jitter for organic layouts\nv1.0");
    };

    // Resizing
    pal.onResizing = pal.onResize = function(){ pal.layout.resize(); };

    // Initialize origin fields with current comp center if available
    var compInit = getActiveComp();
    if (compInit) {
      var cc = compCenter(compInit);
      etOriginX.text = Math.round(cc[0]);
      etOriginY.text = Math.round(cc[1]);
    }

    return pal;
  }

  var ui = buildUI(thisObj);
  if (ui instanceof Window) {
    ui.center();
    ui.show();
  }
})(this);
