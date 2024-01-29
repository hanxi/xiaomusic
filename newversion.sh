version="$1"
sed -i "s/version.*/version = \"$version\"/" ./pyproject.toml
git diff
git add ./pyproject.toml
git commit -m "new version v$version"
git tag v$version
#git push --tags
