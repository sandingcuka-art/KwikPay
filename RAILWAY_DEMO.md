# Railway checkout demo

This service demonstrates a merchant request, customer wallet sharing and explicit demo confirmation. It does not create an Open Payments grant or send money. The merchant app stores the most recent 100 confirmed demos on that device, provided its request screen is open and polling when confirmation arrives. It is not a production API: anyone who knows the service URL can create requests, request data is kept in one process for five minutes, and restarts discard it. Do not use real customer information.

Deploy only the three demo files, rather than the full working directory, so local wallet keys, databases and unrelated work are not uploaded:

```sh
stage_dir=$(mktemp -d)
cp mobile_demo_api.py payment_plan.py "$stage_dir/"
cp railway-demo.Dockerfile "$stage_dir/Dockerfile"
railway up "$stage_dir" --path-as-root --project 27f6718e-f2dc-43f4-bf63-46154d2be932 --environment production --service checkout-demo --detach -m 'Deploy mobile checkout demo'
```

The Railway service must set `PUBLIC_ORIGIN` to its HTTPS origin and pass `PORT`. Its health check is `/health`. Build each Android app against that same origin:

```sh
flutter build apk --debug --dart-define=KWIKPAY_API_ORIGIN=https://checkout-demo-production.up.railway.app
```

The default build continues to use the local USB demo. Hosted builds require internet access on both phones.
