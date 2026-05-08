import html as html_module
import streamlit as st
import streamlit.components.v1 as components


def inject_localstorage_reader():
    """Legacy reader — no longer needed since we use cookies. Kept as no-op for compatibility."""
    pass


def inject_localstorage_writer(name):
    """Save nickname, user_id, current session, and preferences to cookies (persistent across refresh)."""
    safe_name = html_module.escape(name, quote=True)
    uid = st.session_state.user_id
    session_id = st.session_state.get("current_session") or ""
    max_turtles = st.session_state.get("max_turtles", 5)
    # Set cookies with 30-day expiry, SameSite=Lax for security
    components.html(f"""
    <script>
    (function() {{
        const expires = new Date(Date.now() + 30*24*60*60*1000).toUTCString();
        document.cookie = "spp_nickname={safe_name}; path=/; expires=" + expires + "; SameSite=Lax";
        document.cookie = "spp_user_id={uid}; path=/; expires=" + expires + "; SameSite=Lax";
        document.cookie = "spp_session={session_id}; path=/; expires=" + expires + "; SameSite=Lax";
        document.cookie = "spp_max_turtles={max_turtles}; path=/; expires=" + expires + "; SameSite=Lax";
    }})();
    </script>
    """, height=0)


def clear_session_storage():
    """Remove the session cookie (on leave/close)."""
    components.html("""
    <script>
    document.cookie = "spp_session=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    </script>
    """, height=0)


def _inject_egg_click():
    """Hide the spawn_turtle button and wire the 🃏 emoji click to it."""
    components.html("""
    <script>
    (function() {
        const doc = window.parent.document;
        // Inject persistent CSS to hide the spawn_turtle button
        if (!doc.getElementById('spp-egg-hide')) {
            const style = doc.createElement('style');
            style.id = 'spp-egg-hide';
            style.textContent = 'button[kind="secondary"]:has(p)  { /* fallback */ }';
            doc.head.appendChild(style);
        }
        // Hide the spawn_turtle button by finding it
        const btns = doc.querySelectorAll('button');
        let targetBtn = null;
        for (const b of btns) {
            if (b.textContent.trim() === 'spawn_turtle') {
                targetBtn = b;
                // Hide the entire button container up to the block level
                let el = b;
                while (el && el.parentElement) {
                    el.style.display = 'none';
                    if (el.getAttribute && (el.getAttribute('data-testid') === 'stVerticalBlock' || el.getAttribute('data-testid') === 'stHorizontalBlock')) {
                        break;
                    }
                    if (el.getAttribute && el.getAttribute('data-testid') === 'stButton') {
                        el.style.display = 'none';
                        break;
                    }
                    el = el.parentElement;
                }
                break;
            }
        }
        // Wire up the emoji
        const egg = doc.getElementById('spp-egg');
        if (egg && targetBtn) {
            egg._bound = true;
            egg.style.cursor = 'pointer';
            egg.onclick = function() {
                targetBtn.click();
            };
        }
    })();
    </script>
    """, height=0)


def cleanup_turtles():
    """Remove any turtle elements from the parent document."""
    components.html("""
    <script>
    (function() {
        const doc = window.parent.document;
        doc.querySelectorAll('.spp-dvd-turtle').forEach(e => e.remove());
        if (doc._sppTurtleState) {
            doc._sppTurtleState.turtles = [];
            doc._sppTurtleState.animating = false;
        }
        // Remove animation script
        const old = doc.getElementById('spp-turtle-anim');
        if (old) old.remove();
    })();
    </script>
    """, height=0)


def inject_turtle_animation(turtle_count):
    """Inject bouncing turtle animation with collision physics.
    Preserves existing turtles and only adds/removes as needed."""
    components.html(f"""
    <script>
    (function() {{
        const COUNT = {turtle_count};
        const SIZE = 60;
        const doc = window.parent.document;
        const pw = window.parent;
        const W = pw.innerWidth;
        const H = pw.innerHeight;

        // Use a persistent state object on the parent document
        if (!doc._sppTurtleState) {{
            doc._sppTurtleState = {{
                turtles: [],
                animating: false,
                mouseX: -1000, mouseY: -1000,
                mouseVX: 0, mouseVY: 0,
                prevMouseX: -1000, prevMouseY: -1000,
            }};
        }}

        const state = doc._sppTurtleState;
        const turtles = state.turtles;

        // Add new turtles if count increased
        while (turtles.length < COUNT) {{
            const i = turtles.length;
            const el = doc.createElement('div');
            el.textContent = '\U0001f422';
            el.className = 'spp-dvd-turtle';
            el.style.position = 'fixed';
            el.style.fontSize = '50px';
            el.style.zIndex = '99999999';
            el.style.pointerEvents = 'none';
            el.style.transition = 'filter 0.5s';
            doc.body.appendChild(el);
            const speed = 3.0 + i * 0.8;
            const angle = (Math.PI / 4) + i * 0.7;
            turtles.push({{
                el: el,
                x: Math.random() * (W - SIZE),
                y: Math.random() * (H - SIZE),
                vx: Math.cos(angle) * speed,
                vy: Math.sin(angle) * speed,
                hue: i * 72
            }});
        }}

        // Remove excess turtles if count decreased
        while (turtles.length > COUNT) {{
            const removed = turtles.pop();
            removed.el.remove();
        }}

        // Inject everything into parent via script tag (survives iframe destruction)
        if (!state.animating) {{
            state.animating = true;
            // Remove old script if exists
            const old = doc.getElementById('spp-turtle-anim');
            if (old) old.remove();
            const script = doc.createElement('script');
            script.id = 'spp-turtle-anim';
            script.textContent = `
                (function() {{
                    const SIZE = 60;
                    const MOUSE_RADIUS = 50;
                    const MIN_BOUNCE = 1.3;
                    const MOUSE_SPEED_SCALE = 0.27;
                    const MAX_SPEED = 5.0;
                    const s = document._sppTurtleState;

                    // Set up mouse listeners in parent context (survives iframe reloads)
                    if (s && !s._listenersAttached) {{
                        s._listenersAttached = true;
                        document.addEventListener('mousemove', function(e) {{
                            const st = document._sppTurtleState;
                            if (!st) return;
                            st.prevMouseX = st.mouseX;
                            st.prevMouseY = st.mouseY;
                            st.mouseX = e.clientX;
                            st.mouseY = e.clientY;
                            st.mouseVX = st.mouseX - st.prevMouseX;
                            st.mouseVY = st.mouseY - st.prevMouseY;
                        }});
                        document.addEventListener('mouseleave', function() {{
                            const st = document._sppTurtleState;
                            if (!st) return;
                            st.mouseX = -1000; st.mouseY = -1000;
                            st.mouseVX = 0; st.mouseVY = 0;
                        }});
                    }}

                    function animate() {{
                        const s = document._sppTurtleState;
                        if (!s) return;
                        const turtles = s.turtles;
                        if (turtles.length === 0) {{
                            s.animating = false;
                            return;
                        }}

                        const cW = window.innerWidth;
                        const cH = window.innerHeight;

                        for (const t of turtles) {{
                            t.x += t.vx;
                            t.y += t.vy;
                            if (t.x <= 0) {{ t.x = 0; t.vx = Math.abs(t.vx); t.hue = (t.hue + 60) % 360; }}
                            if (t.x >= cW - SIZE) {{ t.x = cW - SIZE; t.vx = -Math.abs(t.vx); t.hue = (t.hue + 60) % 360; }}
                            if (t.y <= 0) {{ t.y = 0; t.vy = Math.abs(t.vy); t.hue = (t.hue + 60) % 360; }}
                            if (t.y >= cH - SIZE) {{ t.y = cH - SIZE; t.vy = -Math.abs(t.vy); t.hue = (t.hue + 60) % 360; }}
                        }}

                        const hitRadius = MOUSE_RADIUS + SIZE / 2;
                        for (const t of turtles) {{
                            const tcx = t.x + SIZE / 2;
                            const tcy = t.y + SIZE / 2;
                            const dx = tcx - s.mouseX;
                            const dy = tcy - s.mouseY;
                            const d = Math.sqrt(dx * dx + dy * dy);
                            if (d < hitRadius && d > 0) {{
                                const nx = dx / d;
                                const ny = dy / d;
                                const mouseSpeed = Math.sqrt(s.mouseVX * s.mouseVX + s.mouseVY * s.mouseVY);
                                const push = Math.max(MIN_BOUNCE, mouseSpeed * MOUSE_SPEED_SCALE);
                                t.vx = nx * push;
                                t.vy = ny * push;
                                t.x = s.mouseX + nx * hitRadius - SIZE / 2;
                                t.y = s.mouseY + ny * hitRadius - SIZE / 2;
                                t.hue = (t.hue + 120) % 360;
                            }}
                        }}

                        for (let i = 0; i < turtles.length; i++) {{
                            for (let j = i + 1; j < turtles.length; j++) {{
                                const a = turtles[i], b = turtles[j];
                                const ddx = a.x - b.x, ddy = a.y - b.y;
                                const d = Math.sqrt(ddx * ddx + ddy * ddy);
                                if (d < SIZE && d > 0) {{
                                    const tvx = a.vx; const tvy = a.vy;
                                    a.vx = b.vx; a.vy = b.vy;
                                    b.vx = tvx; b.vy = tvy;
                                    const overlap = SIZE - d;
                                    const nx = ddx / d, ny = ddy / d;
                                    a.x += nx * overlap / 2;
                                    a.y += ny * overlap / 2;
                                    b.x -= nx * overlap / 2;
                                    b.y -= ny * overlap / 2;
                                    a.hue = (a.hue + 90) % 360;
                                    b.hue = (b.hue + 90) % 360;
                                }}
                            }}
                        }}

                        for (const t of turtles) {{
                            const spd = Math.sqrt(t.vx * t.vx + t.vy * t.vy);
                            if (spd > MAX_SPEED) {{
                                t.vx *= 0.98;
                                t.vy *= 0.98;
                            }}
                        }}

                        for (const t of turtles) {{
                            t.el.style.left = t.x + 'px';
                            t.el.style.top = t.y + 'px';
                            t.el.style.filter = 'hue-rotate(' + t.hue + 'deg)';
                        }}

                        requestAnimationFrame(animate);
                    }}
                    requestAnimationFrame(animate);
                }})();
            `;
            doc.head.appendChild(script);
        }}
    }})();
    </script>
    """, height=0)
