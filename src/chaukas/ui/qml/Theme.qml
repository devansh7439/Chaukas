pragma Singleton
import QtQuick

// Design tokens: every colour, size, radius and duration the interface uses.
// Soft neutral surfaces with one warm copper accent; alert levels always pair a colour
// with an icon and a word, never colour alone.
QtObject {
    // Surfaces
    readonly property color backdrop: "#C9C9C9"
    readonly property color backdropDeep: "#8F8F8F"
    readonly property color panelTop: "#F8F8F8"
    readonly property color panelBottom: "#ECECEC"
    readonly property color surfaceTop: "#EFEFEF"
    readonly property color surface: "#E5E5E5"
    readonly property color raised: "#FFFFFF"
    readonly property color track: "#DCDCDC"
    readonly property color trackSoft: "#EBEBEB"
    readonly property color bubbleUser: "#E2E2E2"
    readonly property color sidebarTop: "#767676"
    readonly property color sidebarBottom: "#383838"
    readonly property color darkTop: "#5E5E5E"
    readonly property color darkBottom: "#2B2B2B"
    readonly property color scrim: "#B3141414"

    // Text (muted text is at least 4.5:1 on every light surface)
    readonly property color ink: "#131313"
    readonly property color inkMuted: "#595959"
    readonly property color inkFaint: "#7C7C7C"
    readonly property color textOnDark: "#FAFAFA"
    readonly property color textOnDarkMuted: "#D6D6D6"
    readonly property color textOnAccent: "#FFFFFF"

    // Brand
    readonly property color accent: "#C4613A"
    readonly property color accentDeep: "#9E4623"
    readonly property color accentSoft: "#F5E1D7"
    readonly property color accentGlow: "#E9A283"
    readonly property color focusRing: "#E38B64"

    // Alert levels
    readonly property var levelColors: ({
        "quiet": "#2E7A52",
        "notice": "#A86A12",
        "warning": "#B8552E",
        "critical": "#B3261E",
        "critical_recovery": "#8A1C17"
    })
    readonly property var levelIcons: ({
        "quiet": "shield-check",
        "notice": "info",
        "warning": "triangle-alert",
        "critical": "octagon-alert",
        "critical_recovery": "octagon-alert"
    })
    function levelColor(level) { return levelColors[level] || accent }
    function levelIcon(level) { return levelIcons[level] || "shield-check" }

    // Type
    readonly property string family: "Plus Jakarta Sans"
    readonly property string familyDevanagari: "Noto Sans Devanagari"
    // Plus Jakarta Sans has no Devanagari; Noto Sans Devanagari covers Hindi and Latin.
    // Switch on the language first (it changes before the Hindi labels arrive), and on the
    // content for Hindi typed while the interface is in English.
    function fontFor(content, language) {
        return language === "hi" || /[ऀ-ॿ]/.test(content) ? familyDevanagari : family
    }
    readonly property int display: 62
    readonly property int title: 28
    readonly property int heading: 21
    readonly property int bodyLarge: 17
    readonly property int body: 15
    readonly property int label: 13
    readonly property int caption: 12

    // Shape
    readonly property int radiusShell: 44
    readonly property int radiusCard: 30
    readonly property int radiusInner: 22
    readonly property int radiusSmall: 14

    // Spacing: 4 pt grid
    readonly property int s1: 4
    readonly property int s2: 8
    readonly property int s3: 12
    readonly property int s4: 16
    readonly property int s5: 20
    readonly property int s6: 24
    readonly property int s7: 32
    readonly property int s8: 40

    // Motion
    readonly property int fast: 150
    readonly property int normal: 240

    // Minimum click target
    readonly property int target: 44

    function icon(name, colour) {
        return "image://icon/" + name + "/" + String(colour).replace("#", "").slice(-6)
    }
}
