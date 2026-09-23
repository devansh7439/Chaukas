import QtQuick
import QtQuick.Layouts
import Chaukas

// Privacy panel (blueprint 6.9): where each kind of data is processed, the listening
// indicator with a pause switch, and the session wipe.
Item {
    id: root
    signal endSession()

    ColumnLayout {
        anchors.fill: parent
        spacing: 26

        AppText {
            Layout.fillWidth: true
            text: dashboard.labels.privacy_title
            font.pixelSize: Theme.display - 6
            font.weight: Font.DemiBold
            font.letterSpacing: -0.5
            Accessible.role: Accessible.Heading
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 4
            columnSpacing: 20
            rowSpacing: 20
            Repeater {
                model: [
                    { "icon": "headphones", "label": dashboard.labels.privacy_audio, "value": dashboard.labels.privacy_local },
                    { "icon": "monitor", "label": dashboard.labels.privacy_screen, "value": dashboard.labels.privacy_local },
                    { "icon": "cpu", "label": dashboard.labels.privacy_ai, "value": dashboard.labels.privacy_local },
                    { "icon": "wifi-off", "label": dashboard.labels.privacy_cloud, "value": dashboard.labels.privacy_none }
                ]
                Card {
                    id: tile
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: 190
                    elevation: 1
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 24
                        spacing: 6
                        Rectangle {
                            width: 56; height: 56; radius: 28
                            color: Theme.accentSoft
                            Icon { anchors.centerIn: parent; name: tile.modelData.icon; tint: Theme.accentDeep; size: 26 }
                        }
                        Item { Layout.fillHeight: true }
                        AppText { text: tile.modelData.label; color: Theme.inkMuted; font.pixelSize: Theme.body }
                        AppText {
                            Layout.fillWidth: true
                            text: tile.modelData.value
                            font.pixelSize: Theme.heading
                            font.weight: Font.DemiBold
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 20

            Card {
                Layout.fillWidth: true
                Layout.preferredHeight: 150
                color: Theme.darkTop
                colorBottom: Theme.darkBottom
                elevation: 1.2
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 28
                    spacing: 20
                    Rectangle {
                        width: 64; height: 64; radius: 32
                        color: dashboard.view.paused ? Qt.rgba(1, 1, 1, 0.14) : "#3FAE72"
                        Icon { anchors.centerIn: parent; name: dashboard.view.paused ? "mic-off" : "mic"; tint: Theme.textOnDark; size: 28 }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        AppText {
                            text: dashboard.view.paused ? dashboard.labels.paused : dashboard.labels.listening
                            color: Theme.textOnDark
                            font.pixelSize: Theme.title - 2
                            font.weight: Font.DemiBold
                        }
                        AppText {
                            Layout.fillWidth: true
                            text: dashboard.liveStatus.length > 0 ? dashboard.liveStatus
                                                                   : dashboard.view.statusLine
                            color: Theme.textOnDarkMuted
                            font.pixelSize: Theme.body
                            maximumLineCount: 2
                        }
                    }
                    PillButton {
                        variant: "ghost"
                        iconName: dashboard.view.paused ? "play" : "pause"
                        text: dashboard.view.paused ? dashboard.labels.action_resume : dashboard.labels.action_pause
                        onClicked: dashboard.togglePause()
                    }
                }
            }

            Card {
                Layout.preferredWidth: 360
                Layout.preferredHeight: 150
                elevation: 1
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 24
                    spacing: 12
                    AppText {
                        Layout.fillWidth: true
                        text: dashboard.labels.end_hint
                        font.pixelSize: Theme.bodyLarge
                        font.weight: Font.DemiBold
                    }
                    PillButton {
                        variant: "danger"
                        iconName: "trash-2"
                        text: dashboard.labels.action_end
                        onClicked: root.endSession()
                    }
                }
            }
        }

        AppText {
            Layout.fillWidth: true
            Layout.maximumWidth: 820
            text: dashboard.labels.privacy_note
            color: Theme.inkMuted
            font.pixelSize: Theme.bodyLarge
            lineHeight: 1.25
        }

        Item { Layout.fillHeight: true }
    }
}
