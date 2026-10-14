def desensitize_user_name(user):
    user = str(user)
    if len(user) <= 8:
        length = max(len(user) // 3, 1)
        return f"{user[:length]}***{user[-length:]}"
    return f"{user[:3]}****{user[-4:]}"
