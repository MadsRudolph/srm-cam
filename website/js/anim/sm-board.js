/* Shared parts of the solder mask page's drawings (solder-mask.html).

   The board is a real one: the 78 openings srm-cam writes for a 54 x 45.8 mm ESP32
   test board, in the file's own frame, so mirrored and shrunk 0.1 mm per side:
   [x, y, w, h, corner radius], mm, with the outline's corner at 0, 0. CHECK picks the
   three far apart and well out of line that the alignment check uses. */
(function () {
  "use strict";
  var A = window.SRMAnim, C = A.C;

  var PADS = [[3,6.96,1.6,1.6,0],[3,9.5,1.6,1.6,.8],[3,12.84,1.4,1.4,.7],[3,23,1.4,1.4,.7],[4,27,1.8,1.8,.9],[4,31.5,1.8,1.8,.9],[5.84,35.5,1.4,1.4,.7],[10.5,27,1.8,1.8,.9],[10.5,31.5,1.8,1.8,.9],[14,31,1.4,1.4,.7],[16,31,1.4,1.4,.15],[16,35.5,1.4,1.4,.7],[17.5,40.48,1.4,1.4,.7],[17.5,42.98,1.4,1.4,.7],[21.25,27.74,1.3,.7,0],[21.25,29.01,1.3,.7,0],[21.25,30.28,1.3,.7,0],[21.25,31.55,1.3,.7,0],[21.25,32.82,1.3,.7,0],[21.25,34.09,1.3,.7,0],[21.25,35.36,1.3,.7,0],[21.25,36.63,1.3,.7,0],[21.25,37.9,1.3,.7,0],[21.25,39.17,1.3,.7,0],[21.25,40.44,1.3,.7,0],[21.25,41.71,1.3,.7,0],[21.25,42.98,1.3,.7,0],[21.25,44.25,1.3,.7,0],[24.29,26.49,.7,1.3,0],[24.5,4.5,1.4,1.4,.7],[24.5,14.66,1.4,1.4,.7],[25.56,26.49,.7,1.3,0],[26.83,26.49,.7,1.3,0],[27.84,4.5,1.4,1.4,.7],[28.1,26.49,.7,1.3,0],[29.32,36.91,4,4,0],[29.37,26.49,.7,1.3,0],[30.18,13.34,1.6,1.6,0],[30.64,26.49,.7,1.3,0],[31.91,26.49,.7,1.3,0],[32.72,13.34,1.6,1.6,.8],[33.18,26.49,.7,1.3,0],[34.45,26.49,.7,1.3,0],[35.72,13.34,1.4,1.4,.7],[35.72,23.5,1.4,1.4,.7],[35.72,26.49,.7,1.3,0],[38,4.5,1.4,1.4,.7],[38.75,27.74,1.3,.7,0],[38.75,29.01,1.3,.7,0],[38.75,30.28,1.3,.7,0],[38.75,31.55,1.3,.7,0],[38.75,32.82,1.3,.7,0],[38.75,34.09,1.3,.7,0],[38.75,35.36,1.3,.7,0],[38.75,36.63,1.3,.7,0],[38.75,37.9,1.3,.7,0],[38.75,39.17,1.3,.7,0],[38.75,40.44,1.3,.7,0],[38.75,41.71,1.3,.7,0],[38.75,42.98,1.3,.7,0],[38.75,44.25,1.3,.7,0],[39,13.34,1.4,1.4,.7],[39,23.5,1.4,1.4,.7],[41.92,4.5,1.7,1.8,0],[42.46,10.5,1.4,1.4,.7],[44,19.5,1.8,1.8,.9],[44,24,1.8,1.8,.9],[44.46,4.5,1.7,1.8,.85],[44.46,10.5,1.4,1.4,.15],[47,4.5,1.7,1.8,.85],[48.5,34.82,1.5,1.5,.75],[48.5,37.36,1.5,1.5,.75],[48.5,39.9,1.5,1.5,.75],[48.5,42.44,1.5,1.5,0],[49.5,9,1.4,1.4,.7],[50.5,19.5,1.8,1.8,.9],[50.5,24,1.8,1.8,.9],[51.5,9,1.4,1.4,.15]];

  /* A colour between two #rrggbb colours. */
  function mix(a, b, t) {
    t = A.clamp(t, 0, 1);
    var out = "#";
    for (var i = 1; i < 7; i += 2) {
      var x = parseInt(a.substr(i, 2), 16), y = parseInt(b.substr(i, 2), 16);
      out += ("0" + Math.round(x + (y - x) * t).toString(16)).slice(-2);
    }
    return out;
  }

  /* Add one pad to parent as an SVG rect, at a mm-to-pixel scale. Returns the rect. */
  function pad(parent, p, sx, sy, k, attrs) {
    var a = { x: sx(p[0]) - p[2] * k / 2, y: sy(p[1]) - p[3] * k / 2,
              width: p[2] * k, height: p[3] * k, rx: p[4] * k };
    for (var n in attrs) a[n] = attrs[n];
    return A.el(parent, "rect", a);
  }

  /* Draw t = 0..dur once while on screen; replay() runs it again. With reduced motion
     the last frame shows straight away, as A.loop promises. */
  function player(host, dur, draw) {
    var lp = null;
    function tick(t) {
      draw(Math.min(t, dur));
      if (t >= dur && lp) lp.stop();
    }
    if (!A.reduced) draw(0);
    lp = A.loop(host, tick, dur);
    return { replay: function () { lp.restart(); } };
  }

  window.SMBoard = {
    W: 54, H: 45.8, PADS: PADS, CHECK: [0, 60, 63],
    INK: "#2f6d55", INK_WET: "#49a07d", INK_DEEP: "#1f4a39", UNDER: "#8a7a3e", UV: "#a78bfa",
    mix: mix, pad: pad, player: player
  };
})();
