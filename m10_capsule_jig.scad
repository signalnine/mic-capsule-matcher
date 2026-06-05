// PCM-M10 capsule test-jig — capsule holder / acoustic coupler end
// Units: mm.  Capsule drops into the top well, rests on the shoulder
// with its front inlet facing the bore; sound enters from the bottom.

/* ---------- parameters ---------- */
capsule_dia   = 9.80;  // capsule bore (AOM-5024L 9.72, +0.08 slip clearance)
well_depth    = 4;     // depth of capsule well (this floor is the stop)
bore_dia      = 7.74;   // inner acoustic channel
bore_len      = 8;     // channel length below the well   <- tweak

outer_top_dia = 20;    // body OD at capsule (top) end     <- guessed, tweak
outer_bot_dia = 14;    // body OD at source (bottom) end   <- guessed, tweak

eps = 0.05;            // boolean overlap fudge
$fn = 160;             // circle smoothness

/* ---------- derived ---------- */
total_h = well_depth + bore_len;

/* ---------- model ---------- */
difference() {
    // tapered outer body (wide at the capsule end)
    cylinder(h = total_h, d1 = outer_bot_dia, d2 = outer_top_dia);

    // capsule well cut from the top; its floor is the stop shoulder
    translate([0, 0, total_h - well_depth])
        cylinder(h = well_depth + eps, d = capsule_dia);

    // acoustic channel, open at the bottom, meeting the well floor
    translate([0, 0, -eps])
        cylinder(h = bore_len + eps, d = bore_dia);
}
