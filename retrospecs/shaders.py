"""CRT shader definitions — vertex shader + 5 fragment shaders."""

# Common vertex shader for fullscreen quad
VERTEX_SHADER = """
#version 330 core

layout(location = 0) in vec2 aPos;
layout(location = 1) in vec2 aTexCoord;

out vec2 vTexCoord;

void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
    vTexCoord = aTexCoord;
}
"""

# ---------------------------------------------------------------------------
# 1. Basic Scanlines — horizontal line darkening + vignette
# ---------------------------------------------------------------------------
FRAG_SCANLINES = """
#version 330 core

in vec2 vTexCoord;
out vec4 FragColor;

uniform sampler2D uTexture;
uniform vec2 uResolution;
uniform float uTime;

void main() {
    vec3 col = texture(uTexture, vTexCoord).rgb;

    // Scanline: darken every other pixel row
    float scanline = sin(vTexCoord.y * uResolution.y * 1.57080) * 0.5 + 0.5;
    scanline = mix(0.65, 1.0, scanline);
    col *= scanline;

    // Vignette
    vec2 uv = vTexCoord * 2.0 - 1.0;
    float vig = 1.0 - dot(uv * 0.55, uv * 0.55);
    col *= clamp(vig, 0.0, 1.0);

    // Slight brightness boost to compensate for scanline darkening
    col *= 1.15;

    FragColor = vec4(col, 1.0);
}
"""

# ---------------------------------------------------------------------------
# 2. CRT Curvature — barrel distortion + scanlines + chromatic aberration
# ---------------------------------------------------------------------------
FRAG_CURVATURE = """
#version 330 core

in vec2 vTexCoord;
out vec4 FragColor;

uniform sampler2D uTexture;
uniform vec2 uResolution;
uniform float uTime;

vec2 barrel(vec2 uv, float amt) {
    vec2 cc = uv - 0.5;
    float dist = dot(cc, cc);
    return uv + cc * dist * amt;
}

void main() {
    float distortion = 0.15;
    vec2 uv = barrel(vTexCoord, distortion);

    // Black outside curved screen area
    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) {
        FragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    // Chromatic aberration
    float ca = 0.002;
    float r = texture(uTexture, barrel(vTexCoord, distortion + ca)).r;
    float g = texture(uTexture, uv).g;
    float b = texture(uTexture, barrel(vTexCoord, distortion - ca)).b;
    vec3 col = vec3(r, g, b);

    // Scanlines
    float scan = sin(uv.y * uResolution.y * 1.57080) * 0.5 + 0.5;
    col *= mix(0.7, 1.0, scan);

    // Corner shadow
    vec2 edge = smoothstep(0.0, 0.05, uv) * (1.0 - smoothstep(0.95, 1.0, uv));
    col *= edge.x * edge.y;

    col *= 1.1;
    FragColor = vec4(col, 1.0);
}
"""

# ---------------------------------------------------------------------------
# 3. Phosphor Grid — RGB dot triad mask + bloom + scanlines
# ---------------------------------------------------------------------------
FRAG_PHOSPHOR = """
#version 330 core

in vec2 vTexCoord;
out vec4 FragColor;

uniform sampler2D uTexture;
uniform vec2 uResolution;
uniform float uTime;

void main() {
    vec3 col = texture(uTexture, vTexCoord).rgb;

    // Simple bloom: average nearby pixels
    vec2 px = 1.0 / uResolution;
    vec3 bloom = vec3(0.0);
    bloom += texture(uTexture, vTexCoord + vec2(-px.x, 0.0)).rgb;
    bloom += texture(uTexture, vTexCoord + vec2( px.x, 0.0)).rgb;
    bloom += texture(uTexture, vTexCoord + vec2(0.0, -px.y)).rgb;
    bloom += texture(uTexture, vTexCoord + vec2(0.0,  px.y)).rgb;
    bloom *= 0.25;
    col = mix(col, bloom, 0.2);

    // Phosphor triad mask (RGB dots repeating every 3 pixels)
    int px_x = int(gl_FragCoord.x) % 3;
    vec3 mask = vec3(0.4);
    if (px_x == 0) mask.r = 1.0;
    else if (px_x == 1) mask.g = 1.0;
    else mask.b = 1.0;

    // Offset every other row for triad pattern
    int px_y = int(gl_FragCoord.y) % 2;
    if (px_y == 1) {
        int px_x2 = (int(gl_FragCoord.x) + 1) % 3;
        mask = vec3(0.4);
        if (px_x2 == 0) mask.r = 1.0;
        else if (px_x2 == 1) mask.g = 1.0;
        else mask.b = 1.0;
    }

    col *= mask;

    // Scanlines
    float scan = sin(vTexCoord.y * uResolution.y * 1.57080) * 0.5 + 0.5;
    col *= mix(0.75, 1.0, scan);

    // Compensate brightness
    col *= 1.6;

    FragColor = vec4(col, 1.0);
}
"""

# ---------------------------------------------------------------------------
# 4. Aperture Grille — vertical RGB stripes + damper wires (Trinitron)
# ---------------------------------------------------------------------------
FRAG_APERTURE = """
#version 330 core

in vec2 vTexCoord;
out vec4 FragColor;

uniform sampler2D uTexture;
uniform vec2 uResolution;
uniform float uTime;

void main() {
    vec3 col = texture(uTexture, vTexCoord).rgb;

    // Vertical RGB stripe mask (aperture grille)
    int px_x = int(gl_FragCoord.x) % 3;
    vec3 mask = vec3(0.3);
    if (px_x == 0) mask.r = 1.0;
    else if (px_x == 1) mask.g = 1.0;
    else mask.b = 1.0;
    col *= mask;

    // Horizontal damper wire shadows (two thin dark horizontal lines)
    float y_norm = gl_FragCoord.y / uResolution.y;
    float wire1 = smoothstep(0.0, 0.003, abs(y_norm - 0.33));
    float wire2 = smoothstep(0.0, 0.003, abs(y_norm - 0.66));
    col *= min(wire1, wire2) * 0.15 + 0.85;

    // Very subtle scanlines (Trinitron had minimal scanlines)
    float scan = sin(vTexCoord.y * uResolution.y * 1.57080) * 0.5 + 0.5;
    col *= mix(0.85, 1.0, scan);

    // Compensate brightness
    col *= 1.5;

    FragColor = vec4(col, 1.0);
}
"""

# ---------------------------------------------------------------------------
# 5. Retro Mono — green phosphor + glow + heavy scanlines + flicker
# ---------------------------------------------------------------------------
FRAG_MONO = """
#version 330 core

in vec2 vTexCoord;
out vec4 FragColor;

uniform sampler2D uTexture;
uniform vec2 uResolution;
uniform float uTime;

void main() {
    vec3 col = texture(uTexture, vTexCoord).rgb;

    // Convert to luminance
    float lum = dot(col, vec3(0.299, 0.587, 0.114));

    // Apply green phosphor color (P1 phosphor)
    vec3 green = vec3(0.1, 1.0, 0.2) * lum;

    // Glow/bloom
    vec2 px = 1.0 / uResolution;
    float bloom_lum = 0.0;
    for (int dx = -2; dx <= 2; dx++) {
        for (int dy = -2; dy <= 2; dy++) {
            vec3 s = texture(uTexture, vTexCoord + vec2(float(dx), float(dy)) * px).rgb;
            bloom_lum += dot(s, vec3(0.299, 0.587, 0.114));
        }
    }
    bloom_lum /= 25.0;
    vec3 glow = vec3(0.1, 1.0, 0.2) * bloom_lum;
    green = mix(green, glow, 0.3);

    // Heavy scanlines
    float scan = sin(vTexCoord.y * uResolution.y * 1.57080) * 0.5 + 0.5;
    green *= mix(0.45, 1.0, scan);

    // Flicker
    float flicker = 0.97 + 0.03 * sin(uTime * 8.0);
    green *= flicker;

    // Vignette
    vec2 uv = vTexCoord * 2.0 - 1.0;
    float vig = 1.0 - dot(uv * 0.6, uv * 0.6);
    green *= clamp(vig, 0.0, 1.0);

    green *= 1.3;

    FragColor = vec4(green, 1.0);
}
"""

# Shader registry — ordered list of available shaders
SHADERS = [
    {
        "name": "Basic Scanlines",
        "short": "SCN",
        "fragment": FRAG_SCANLINES,
        "description": "Horizontal line darkening with vignette",
    },
    {
        "name": "CRT Curvature",
        "short": "CRV",
        "fragment": FRAG_CURVATURE,
        "description": "Barrel distortion with chromatic aberration",
    },
    {
        "name": "Phosphor Grid",
        "short": "PHO",
        "fragment": FRAG_PHOSPHOR,
        "description": "RGB dot triad mask with bloom",
    },
    {
        "name": "Aperture Grille",
        "short": "APR",
        "fragment": FRAG_APERTURE,
        "description": "Vertical RGB stripes (Trinitron style)",
    },
    {
        "name": "Retro Mono",
        "short": "MON",
        "fragment": FRAG_MONO,
        "description": "Green phosphor with glow and flicker",
    },
]
