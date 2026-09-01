# Validation Endpoint:
https://HOST/api/access-control/v2/validation/?deviceIdentifier=GATE_IP&mediaIdentifier=RFID_MEDIA_ID

# Example Response:
{"validationCode":"NO_PERMISSION_AVAILABLE","reason":"No permission available for media id: E00401090336A8CD","mediaId":"69cc2f6b192ffsc915484bop","mediaIdentifier":"E00401090336A8CD","variantName":null,"permissionId":null,"clientName":"John Doe","clientAge":29,"clientPhotoUrl":"https://HOST/api/pictures/client.png","provider":"MTNOS","hotlistCode":null,"behaviorsByType":null,"valid":false}

# Config:
format should be toml

mntos-server -> HOST
control-device -> GATE_IP
logo -> logo to be used for web kiosk view