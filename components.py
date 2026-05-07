import html as html_module
import streamlit as st
import streamlit.components.v1 as components


def inject_localstorage_reader():
    """Legacy reader — no longer needed since we use cookies. Kept as no-op for compatibility."""
    pass


def inject_localstorage_writer(name):
    """Save nickname, user_id, and current session to cookies (persistent across refresh)."""
    safe_name = html_module.escape(name, quote=True)
    uid = st.session_state.user_id
    session_id = st.session_state.get("current_session") or ""
    # Set cookies with 30-day expiry, SameSite=Lax for security
    components.html(f"""
    <script>
    (function() {{
        const expires = new Date(Date.now() + 30*24*60*60*1000).toUTCString();
        document.cookie = "spp_nickname={safe_name}; path=/; expires=" + expires + "; SameSite=Lax";
        document.cookie = "spp_user_id={uid}; path=/; expires=" + expires + "; SameSite=Lax";
        document.cookie = "spp_session={session_id}; path=/; expires=" + expires + "; SameSite=Lax";
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


def cleanup_turtles():
    """Remove any turtle elements from the parent document."""
    components.html("""
    <script>
    (function() {
        const doc = window.parent.document;
        doc.querySelectorAll('.spp-dvd-turtle').forEach(e => e.remove());
    })();
    </script>
    """, height=0)


def inject_turtle_animation(turtle_count):
    """Inject bouncing turtle animation with collision physics."""
    components.html(f"""
    <script>
    (function() {{
        const COUNT = {turtle_count};
        const SIZE = 60;
        const doc = window.parent.document;
        const W = window.parent.innerWidth;
        const H = window.parent.innerHeight;
        const turtles = [];

        // Remove previous turtles if any
        doc.querySelectorAll('.spp-dvd-turtle').forEach(e => e.remove());

        for (let i = 0; i < COUNT; i++) {{
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

        function dist(a, b) {{
            const dx = a.x - b.x;
            const dy = a.y - b.y;
            return Math.sqrt(dx * dx + dy * dy);
        }}

        function animate() {{
            const cW = window.parent.innerWidth;
            const cH = window.parent.innerHeight;

            for (const t of turtles) {{
                t.x += t.vx;
                t.y += t.vy;
                if (t.x <= 0) {{ t.x = 0; t.vx = Math.abs(t.vx); t.hue = (t.hue + 60) % 360; }}
                if (t.x >= cW - SIZE) {{ t.x = cW - SIZE; t.vx = -Math.abs(t.vx); t.hue = (t.hue + 60) % 360; }}
                if (t.y <= 0) {{ t.y = 0; t.vy = Math.abs(t.vy); t.hue = (t.hue + 60) % 360; }}
                if (t.y >= cH - SIZE) {{ t.y = cH - SIZE; t.vy = -Math.abs(t.vy); t.hue = (t.hue + 60) % 360; }}
            }}

            for (let i = 0; i < turtles.length; i++) {{
                for (let j = i + 1; j < turtles.length; j++) {{
                    const a = turtles[i], b = turtles[j];
                    const d = dist(a, b);
                    if (d < SIZE && d > 0) {{
                        const tvx = a.vx; const tvy = a.vy;
                        a.vx = b.vx; a.vy = b.vy;
                        b.vx = tvx; b.vy = tvy;
                        const overlap = SIZE - d;
                        const dx = (a.x - b.x) / d;
                        const dy = (a.y - b.y) / d;
                        a.x += dx * overlap / 2;
                        a.y += dy * overlap / 2;
                        b.x -= dx * overlap / 2;
                        b.y -= dy * overlap / 2;
                        a.hue = (a.hue + 90) % 360;
                        b.hue = (b.hue + 90) % 360;
                    }}
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
    </script>
    """, height=0)
