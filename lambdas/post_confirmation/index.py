import boto3

cognito = boto3.client("cognito-idp")


def handler(event, context):
    # Cognito calls this right after a user confirms their sign-up.
    # Every new user starts as a fan. An admin can change it later.
    if event.get("triggerSource") == "PostConfirmation_ConfirmSignUp":
        try:
            cognito.admin_add_user_to_group(
                UserPoolId=event["userPoolId"],
                Username=event["userName"],
                GroupName="fan",
            )
        except Exception as e:
            # Never block the sign-up: just log it (an admin can fix the group).
            print("Could not add user to fan group:", repr(e))
    # Cognito needs the same event back.
    return event
