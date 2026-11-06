import QtQuick
Image {
    id: root
    property string appId: ""
    property string iconName: ""
    property var iconCandidates: IconResolver.candidates(iconName).concat(IconResolver.candidates(appId))
    property int candidateIndex: 0
    readonly property bool failedLoad: status === Image.Error
    source: candidateIndex < iconCandidates.length ? iconCandidates[candidateIndex] : ""
    onIconCandidatesChanged: candidateIndex = 0
    onStatusChanged: {
        if (status === Image.Error) Qt.callLater(function() {
            if (root.status === Image.Error && root.candidateIndex < root.iconCandidates.length)
                root.candidateIndex++;
        });
    }
}
