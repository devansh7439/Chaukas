import QtQuick
import QtQuick.Layouts
import Chaukas

// "Let the user decide": safe next steps that expand in place. Chaukas never places calls
// or blocks anything; it shows the user what to do and who to call from their own phone.
ColumnLayout {
    id: root
    property string open: ""        // "", "verify", "contact" or "helpline"
    property bool large: false

    spacing: 14

    Flow {
        Layout.fillWidth: true
        spacing: 10
        PillButton {
            text: dashboard.labels.verify_btn
            iconName: "circle-check"
            variant: root.open === "verify" ? "primary" : "secondary"
            onClicked: root.open = root.open === "verify" ? "" : "verify"
        }
        PillButton {
            text: dashboard.labels.contact_btn
            iconName: "user-round"
            variant: root.open === "contact" ? "primary" : "secondary"
            onClicked: root.open = root.open === "contact" ? "" : "contact"
        }
        PillButton {
            text: dashboard.labels.helpline_btn
            iconName: "phone"
            variant: root.open === "helpline" ? "primary" : "secondary"
            onClicked: root.open = root.open === "helpline" ? "" : "helpline"
        }
    }

    Card {
        visible: root.open.length > 0
        Layout.fillWidth: true
        Layout.preferredHeight: detail.implicitHeight + 36
        radius: Theme.radiusInner
        color: Theme.raised
        elevation: 0.6

        ColumnLayout {
            id: detail
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.margins: 20
            spacing: 6

            // Verify independently
            AppText {
                visible: root.open === "verify"
                Layout.fillWidth: true
                text: dashboard.labels.verify_detail
                font.pixelSize: root.large ? Theme.bodyLarge + 1 : Theme.body
                lineHeight: 1.2
            }

            // Trusted contact, shown large
            AppText {
                visible: root.open === "contact" && dashboard.contactNumber.length > 0
                Layout.fillWidth: true
                text: dashboard.contactName
                color: Theme.inkMuted
                font.pixelSize: Theme.bodyLarge
                font.weight: Font.DemiBold
            }
            AppText {
                visible: root.open === "contact" && dashboard.contactNumber.length > 0
                Layout.fillWidth: true
                text: dashboard.contactNumber
                font.pixelSize: root.large ? 40 : 30
                font.weight: Font.Bold
                font.features: { "tnum": 1 }
            }
            AppText {
                visible: root.open === "contact"
                Layout.fillWidth: true
                text: dashboard.contactNumber.length > 0 ? dashboard.labels.contact_call : dashboard.labels.contact_missing
                color: Theme.inkMuted
                font.pixelSize: Theme.body
            }

            // Helpline
            AppText {
                visible: root.open === "helpline"
                text: "1930"
                font.pixelSize: root.large ? 40 : 30
                font.weight: Font.Bold
            }
            AppText {
                visible: root.open === "helpline"
                Layout.fillWidth: true
                text: dashboard.labels.helpline_detail
                color: Theme.inkMuted
                font.pixelSize: Theme.body
            }
        }
    }
}
