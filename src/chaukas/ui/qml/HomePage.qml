import QtQuick
import QtQuick.Layouts
import Chaukas

// Home: protection status, risk, actions, the live call, and a summary of this call.
Item {
    id: root
    signal openWhy()
    signal openPrivacy()
    signal showSheet(string kind)

    readonly property var view: dashboard.view
    readonly property bool audioProblem: dashboard.liveStatus.indexOf("Audio unavailable") === 0

    ColumnLayout {
        anchors.fill: parent
        spacing: 24

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 28

            // Left column: status, risk, actions
            ColumnLayout {
                Layout.preferredWidth: root.width * 0.46
                Layout.maximumWidth: 600
                Layout.fillHeight: true
                spacing: 18

                AppText {
                    id: headline
                    Layout.fillWidth: true
                    Layout.rightMargin: 40
                    text: root.view.headline
                    font.pixelSize: Math.min(Theme.display, Math.max(44, root.width * 0.05))
                    font.weight: Font.DemiBold
                    font.letterSpacing: -0.6
                    lineHeight: 0.98
                    maximumLineCount: 2
                    Accessible.role: Accessible.Heading
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Rectangle {
                        width: 10
                        height: 10
                        radius: 5
                        color: root.view.paused ? Theme.inkFaint
                             : root.audioProblem ? Theme.levelColor("warning") : "#3FAE72"
                    }
                    AppText {
                        Layout.fillWidth: true
                        text: root.view.statusLine
                        color: Theme.inkMuted
                        font.pixelSize: Theme.body
                        maximumLineCount: 2
                    }
                }

                // Live mode: what is being listened to, or what went wrong.
                AppText {
                    visible: dashboard.liveStatus.length > 0
                    Layout.fillWidth: true
                    Layout.leftMargin: 20
                    text: dashboard.liveStatus
                    color: root.audioProblem ? Theme.levelColor("warning") : Theme.inkFaint
                    font.pixelSize: Theme.label
                    maximumLineCount: 2
                }

                Item { Layout.fillHeight: true; Layout.minimumHeight: 0 }

                RiskCard {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 190
                    onExplain: root.openWhy()
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 124
                    Layout.maximumHeight: 124
                    spacing: 10
                    ActionTile {
                        Layout.fillWidth: true
                        Layout.maximumWidth: 108
                        Layout.fillHeight: true
                        iconName: root.view.paused ? "play" : "pause"
                        label: root.view.paused ? dashboard.labels.action_resume : dashboard.labels.action_pause
                        checked: root.view.paused
                        onClicked: dashboard.togglePause()
                    }
                    ActionTile {
                        Layout.fillWidth: true
                        Layout.maximumWidth: 108
                        Layout.fillHeight: true
                        iconName: "trash-2"
                        label: dashboard.labels.action_end
                        onClicked: root.showSheet("end")
                    }
                    ActionTile {
                        Layout.fillWidth: true
                        Layout.maximumWidth: 108
                        Layout.fillHeight: true
                        iconName: "user-round"
                        label: dashboard.labels.action_contact
                        onClicked: root.showSheet("contact")
                    }
                    ActionTile {
                        Layout.fillWidth: true
                        Layout.maximumWidth: 108
                        Layout.fillHeight: true
                        iconName: "phone"
                        label: dashboard.labels.action_helpline
                        onClicked: root.showSheet("helpline")
                    }
                    ActionTile {
                        Layout.fillWidth: true
                        Layout.maximumWidth: 108
                        Layout.fillHeight: true
                        iconName: "lock"
                        label: dashboard.labels.action_privacy
                        onClicked: root.openPrivacy()
                    }
                }
            }

            CallPanel {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 380
            }
        }

        // Summary of this call
        RowLayout {
            Layout.fillWidth: true
            spacing: 16
            AppText {
                text: dashboard.labels.this_call
                font.pixelSize: Theme.title
                font.weight: Font.DemiBold
                wrapMode: Text.NoWrap
                Accessible.role: Accessible.Heading
            }
            Item { Layout.fillWidth: true }
            Segmented {
                options: [
                    { "label": dashboard.labels.range_1m, "value": 60 },
                    { "label": dashboard.labels.range_5m, "value": 300 },
                    { "label": dashboard.labels.range_all, "value": 0 }
                ]
                current: dashboard.historyWindow
                onPicked: (value) => dashboard.setHistoryWindow(value)
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 196
            Layout.minimumHeight: 176
            spacing: 24
            GaugeCard { Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 5 }
            HistoryCard { Layout.fillWidth: true; Layout.fillHeight: true; Layout.preferredWidth: 5 }
            ChainCard { Layout.fillHeight: true; Layout.preferredWidth: 250 }
        }
    }
}
