def auth_context(request):
    user = request.user
    is_auth = bool(user.is_authenticated)
    display_name = ""
    initials = ""
    email = ""
    has_plan = False
    plan_name = ""

    if is_auth:
        email = user.email or ""
        display_name = user.first_name if user.first_name else user.username
        if user.first_name and user.last_name:
            initials = (user.first_name[0] + user.last_name[0]).upper()
        else:
            initials = user.username[:2].upper()

        if hasattr(user, "tenant") and user.tenant:
            sub = user.tenant.get_active_subscription()
            has_plan = bool(sub)
            if sub:
                plan_name = sub.plan.nombre

    return {
        "auth": {
            "is_authenticated": is_auth,
            "username": user.username if is_auth else "",
            "email": email,
            "display_name": display_name,
            "initials": initials,
            "has_plan": has_plan,
            "plan_name": plan_name,
        }
    }
