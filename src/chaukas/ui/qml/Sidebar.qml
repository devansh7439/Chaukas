import QtQuick
import Chaukas

// The dark pill on the left: navigation, and the always-visible listening indicator.
Item {
    id: root
    property int current: 0
    signal navigate(int index)

    readonly property var pages: [
        { "icon": "shield-check", "label": dashboard.labels.nav_home },
        { "icon": "lightbulb", "label": dashboard.labels.nav_why },
        { "icon": "lock", "label": dashboard.labels.nav_privacy },
        { "icon": "settings", "label": dashboard.labels.nav_settings }
    ]

    implicitWidth: 116

    SoftShadow { radius: width / 2; strength: 0.16; offsetY: 8 }

    Rectangle {
        anchors.fill: parent
        radius: width / 2
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.sidebarTop }
            GradientStop { position: 1.0; color: Theme.sidebarBottom }
        }

        Column {
            anchors.top: parent.top
            anchors.topMargin: 22
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 22
            Repeater {
                model: root.pages
                SideNavItem {
                    required property var modelData
                    required property int index
                    iconName: modelData.icon
                    label: modelData.label
                    active: root.current === index
                    onClicked: root.navigate(index)
                }
            }
        }

        // Listening indicator: always visible, so the user knows when Chaukas hears them.
        Column {
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 30
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8

            Item {
                width: 44
                height: 44
                anchors.horizontalCenter: parent.horizontalCenter
                Rectangle {
                    id: pulse
                    anchors.centerIn: parent
                    width: 44
                    height: 44
                    radius: 22
                    color: dashboard.view.paused ? "transparent" : Qt.rgba(0.36, 0.82, 0.55, 0.22)
                    SequentialAnimation on scale {
                        running: !dashboard.view.paused
                        loops: Animation.Infinite
                        NumberAnimation { from: 0.7; to: 1.05; duration: 1100; easing.type: Easing.OutCubic }
                        NumberAnimation { from: 1.05; to: 0.7; duration: 1100; easing.type: Easing.InOutCubic }
                    }
                }
                Rectangle {
                    anchors.centerIn: parent
                    width: 30
                    height: 30
                    radius: 15
                    color: dashboard.view.paused ? Qt.rgba(1, 1, 1, 0.14) : "#3FAE72"
                    Icon {
                        anchors.centerIn: parent
                        name: dashboard.view.paused ? "mic-off" : "mic"
                        tint: Theme.textOnDark
                        size: 16
                    }
                }
            }
            AppText {
                anchors.horizontalCenter: parent.horizontalCenter
                text: dashboard.view.paused ? dashboard.labels.paused : dashboard.labels.listening
                color: Theme.textOnDarkMuted
                font.pixelSize: Theme.caption
                wrapMode: Text.NoWrap
            }
        }
    }
}
