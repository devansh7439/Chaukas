import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window
import Chaukas

// Level "critical" / "critical_recovery": a full-screen pause card (blueprint 6.8).
// Friction, not control: no countdown and nothing blocked. "Continue anyway" unlocks once
// the user ticks "I understand this warning".
Window {
    id: root
    objectName: "criticalWindow"
    property var main
    property bool headless: false
    property int fixedWidth: 0
    property int fixedHeight: 0
    readonly property var view: dashboard.view
    readonly property bool recovery: view.level === "critical_recovery"
    readonly property bool shown: view.alertVisible
                                  && (view.level === "critical" || view.level === "critical_recovery")
    readonly property color tone: Theme.levelColor(view.level)

    visibility: shown ? (headless ? Window.Windowed : Window.FullScreen) : Window.Hidden
    width: fixedWidth > 0 ? fixedWidth : Screen.width
    height: fixedHeight > 0 ? fixedHeight : Screen.height
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"
    title: "Chaukas"
    onVisibleChanged: {
        if (visible) {
            understood.checked = false
            decisions.open = ""
            dashboard.protectWindow(root)
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.scrim
    }

    Card {
        id: card
        anchors.centerIn: parent
        width: Math.min(940, root.width - 64)
        height: Math.min(content.implicitHeight + 88, root.height - 48)
        elevation: 3
        color: Theme.panelTop
        colorBottom: Theme.panelBottom
        radius: Theme.radiusShell

        ScrollView {
            id: scroll
            anchors.fill: parent
            anchors.margins: 12
            clip: true
            contentWidth: availableWidth
            contentHeight: content.implicitHeight + 64

            ColumnLayout {
                id: content
                x: 32
                y: 32
                width: scroll.availableWidth - 64
                spacing: 20

                RowLayout {
                    spacing: 14
                    Rectangle {
                        width: 52; height: 52; radius: 26
                        color: root.tone
                        Icon { anchors.centerIn: parent; name: "octagon-alert"; tint: Theme.textOnAccent; size: 28 }
                    }
                    AppText {
                        text: root.view.headline.replace(/[.।]\s*$/, "").toUpperCase()
                        color: root.tone
                        font.pixelSize: Theme.bodyLarge
                        font.weight: Font.ExtraBold
                        font.letterSpacing: 1.6
                        wrapMode: Text.NoWrap
                        Accessible.role: Accessible.Heading
                    }
                }

                AppText {
                    Layout.fillWidth: true
                    text: root.view.objective
                    font.pixelSize: 34
                    font.weight: Font.DemiBold
                    font.letterSpacing: -0.3
                    lineHeight: 1.08
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.track }

                AppText {
                    text: dashboard.labels.why_title
                    color: Theme.inkMuted
                    font.pixelSize: Theme.body
                    font.weight: Font.DemiBold
                }
                ReasonList { Layout.fillWidth: true; reasons: root.view.reasons; large: true }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: facts.implicitHeight + 40
                    radius: Theme.radiusInner
                    color: Theme.accentSoft
                    visible: root.view.fact.length > 0
                    ColumnLayout {
                        id: facts
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.margins: 22
                        spacing: 8
                        AppText {
                            Layout.fillWidth: true
                            text: root.view.fact
                            color: Theme.ink
                            font.pixelSize: Theme.bodyLarge + 2
                            font.weight: Font.DemiBold
                            lineHeight: 1.2
                        }
                        AppText {
                            Layout.fillWidth: true
                            text: root.view.ignoreWarning
                            color: Theme.accentDeep
                            font.pixelSize: Theme.body
                            font.weight: Font.Medium
                        }
                    }
                }

                DecisionPanel { id: decisions; Layout.fillWidth: true; large: true }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 4
                    spacing: 16

                    CheckBox {
                        id: understood
                        text: dashboard.labels.understand
                        font.family: Theme.fontFor(text, dashboard.language)
                        font.pixelSize: Theme.bodyLarge
                        Accessible.name: text
                        indicator: Rectangle {
                            x: understood.leftPadding
                            anchors.verticalCenter: parent.verticalCenter
                            implicitWidth: 28
                            implicitHeight: 28
                            radius: 8
                            color: understood.checked ? root.tone : Theme.raised
                            border.width: understood.activeFocus ? 3 : 2
                            border.color: understood.activeFocus ? Theme.focusRing
                                        : understood.checked ? root.tone : Theme.inkFaint
                            Icon {
                                anchors.centerIn: parent
                                visible: understood.checked
                                name: "check"
                                tint: Theme.textOnAccent
                                size: 18
                            }
                        }
                        contentItem: AppText {
                            leftPadding: understood.indicator.width + 12
                            text: understood.text
                            font.pixelSize: Theme.bodyLarge
                            font.weight: Font.DemiBold
                            verticalAlignment: Text.AlignVCenter
                            wrapMode: Text.NoWrap
                        }
                    }

                    Item { Layout.fillWidth: true }

                    PillButton {
                        text: dashboard.labels.continue
                        iconName: "chevron-right"
                        enabled: understood.checked
                        onClicked: dashboard.dismiss()
                    }
                }
            }
        }
    }
}
